"""add user_reports table for per-user markdown coach files

Revision ID: e3f9a1c82d4b
Revises: d8a4c2e91f0b
Create Date: 2026-08-23 20:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e3f9a1c82d4b"
down_revision: Union[str, Sequence[str], None] = "d8a4c2e91f0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_type=False: SQLAlchemy otherwise emits CREATE TYPE again on
    # create_table even after an explicit checkfirst create (DuplicateObject).
    user_report_type = postgresql.ENUM(
        "progress",
        "errors_log",
        "roadmap",
        "four_week_plan",
        name="user_report_type",
        create_type=False,
    )
    user_report_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "user_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", user_report_type, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("user_id", "report_type", name="uq_user_reports_user_id_report_type"),
    )
    op.create_index("ix_user_reports_user_id", "user_reports", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_reports_user_id", table_name="user_reports")
    op.drop_table("user_reports")
    postgresql.ENUM(name="user_report_type").drop(op.get_bind(), checkfirst=True)
