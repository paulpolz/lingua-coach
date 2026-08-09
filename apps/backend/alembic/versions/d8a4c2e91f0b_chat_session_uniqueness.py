"""dedupe chat sessions and enforce one-per-onboarding / one-per-lesson

Revision ID: d8a4c2e91f0b
Revises: c7be51ce9fe6
Create Date: 2026-08-09 10:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d8a4c2e91f0b"
down_revision: Union[str, Sequence[str], None] = "c7be51ce9fe6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the session with the richest transcript; tie-break on newest created_at.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT cs.id,
                       ROW_NUMBER() OVER (
                           PARTITION BY cs.user_id
                           ORDER BY (
                               SELECT COUNT(*)
                               FROM chat_messages cm
                               WHERE cm.session_id = cs.id
                           ) DESC,
                           cs.created_at DESC
                       ) AS rn
                FROM chat_sessions cs
                WHERE cs.type = 'onboarding'
            )
            DELETE FROM chat_sessions
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT cs.id,
                       ROW_NUMBER() OVER (
                           PARTITION BY cs.user_id, cs.lesson_id
                           ORDER BY (
                               SELECT COUNT(*)
                               FROM chat_messages cm
                               WHERE cm.session_id = cs.id
                           ) DESC,
                           cs.created_at DESC
                       ) AS rn
                FROM chat_sessions cs
                WHERE cs.type = 'lesson' AND cs.lesson_id IS NOT NULL
            )
            DELETE FROM chat_sessions
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )

    op.create_index(
        "uq_chat_sessions_one_onboarding_per_user",
        "chat_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("type = 'onboarding'"),
    )
    op.create_index(
        "uq_chat_sessions_one_lesson_per_user_lesson",
        "chat_sessions",
        ["user_id", "lesson_id"],
        unique=True,
        postgresql_where=sa.text("type = 'lesson' AND lesson_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_chat_sessions_one_lesson_per_user_lesson",
        table_name="chat_sessions",
    )
    op.drop_index(
        "uq_chat_sessions_one_onboarding_per_user",
        table_name="chat_sessions",
    )
