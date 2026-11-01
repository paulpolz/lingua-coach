"""Unique active lesson per user; unique mistake pattern per user.

Two concurrent `POST /lessons/start` calls could both create a lesson, and one chat
reply listing the same `pattern_type` twice could insert duplicate mistakes (which then
broke every later turn with MultipleResultsFound). Both rules now live in the database.

Existing duplicates are merged first, or the unique indexes could not be built:
- extra generating/active lessons (all but the highest lesson_number) become `failed`;
- duplicate mistakes collapse into the most recently seen row, with occurrence counts summed.
The merge is not reversed on downgrade.

Revision ID: 9a1f3c5e7b2d
Revises: c2d5e8f1a3b7
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9a1f3c5e7b2d"
down_revision: str | Sequence[str] | None = "c2d5e8f1a3b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "status IN ('generating', 'active')"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE lessons SET status = 'failed'
        WHERE {_ACTIVE} AND id NOT IN (
            SELECT DISTINCT ON (user_id) id FROM lessons
            WHERE {_ACTIVE}
            ORDER BY user_id, lesson_number DESC
        )
        """
    )
    op.drop_index("ix_lessons_user_id_active", table_name="lessons")
    op.create_index(
        "uq_lessons_user_id_active", "lessons", ["user_id"], unique=True, postgresql_where=sa.text(_ACTIVE)
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER w AS rn,
                   sum(occurrence_count) OVER (PARTITION BY user_id, pattern_type) AS total
            FROM mistakes
            WINDOW w AS (PARTITION BY user_id, pattern_type ORDER BY last_seen_at DESC, id)
        )
        UPDATE mistakes m SET occurrence_count = r.total
        FROM ranked r WHERE m.id = r.id AND r.rn = 1 AND m.occurrence_count <> r.total
        """
    )
    op.execute(
        """
        DELETE FROM mistakes m USING (
            SELECT id, row_number() OVER (
                PARTITION BY user_id, pattern_type ORDER BY last_seen_at DESC, id
            ) AS rn
            FROM mistakes
        ) r
        WHERE m.id = r.id AND r.rn > 1
        """
    )
    op.create_unique_constraint("uq_mistakes_user_id_pattern_type", "mistakes", ["user_id", "pattern_type"])


def downgrade() -> None:
    op.drop_constraint("uq_mistakes_user_id_pattern_type", "mistakes", type_="unique")
    op.drop_index("uq_lessons_user_id_active", table_name="lessons")
    op.create_index("ix_lessons_user_id_active", "lessons", ["user_id"], postgresql_where=sa.text(_ACTIVE))
