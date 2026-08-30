"""add quality_events for thumbs, CSAT, and sampled judges

Revision ID: a8f3c1d92e4b
Revises: f4a7b2c91e3d
Create Date: 2026-08-30 15:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a8f3c1d92e4b"
down_revision: Union[str, Sequence[str], None] = "f4a7b2c91e3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quality_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        # Opaque ids — chat rows are deleted on onboarding accept / lesson finish.
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_quality_events_user_id", "quality_events", ["user_id"])
    op.create_index(
        "ix_quality_events_user_id_created_at", "quality_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_quality_events_kind_message_id", "quality_events", ["kind", "message_id"]
    )
    op.create_index("ix_quality_events_lesson_id", "quality_events", ["lesson_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_events_lesson_id", table_name="quality_events")
    op.drop_index("ix_quality_events_kind_message_id", table_name="quality_events")
    op.drop_index("ix_quality_events_user_id_created_at", table_name="quality_events")
    op.drop_index("ix_quality_events_user_id", table_name="quality_events")
    op.drop_table("quality_events")
