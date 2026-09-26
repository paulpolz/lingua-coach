"""add llm_usage_events for per-user and global LLM limits

Revision ID: b1e7c4a92f30
Revises: a8f3c1d92e4b
Create Date: 2026-09-26 14:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1e7c4a92f30"
down_revision: Union[str, Sequence[str], None] = "a8f3c1d92e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("call_type", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
    op.create_index("ix_llm_usage_events_created_at", "llm_usage_events", ["created_at"])
    op.create_index(
        "ix_llm_usage_events_user_id_created_at_call_type",
        "llm_usage_events",
        ["user_id", "created_at", "call_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_usage_events_user_id_created_at_call_type", table_name="llm_usage_events"
    )
    op.drop_index("ix_llm_usage_events_created_at", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")
