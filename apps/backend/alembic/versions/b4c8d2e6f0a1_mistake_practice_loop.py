"""Mistake practice loop: solid streak and resolution time.

A `solid` practiced result on a mistake pattern pushes its review out one step and moves
the streak at most once per lesson (`last_solid_lesson_id`); solid results in two
different lessons close the pattern (`resolved_at` set, `next_review_at` cleared). A
`shaky` result or a new mistake of the same pattern resets it.

Revision ID: b4c8d2e6f0a1
Revises: 9a1f3c5e7b2d
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c8d2e6f0a1"
down_revision: str | Sequence[str] | None = "9a1f3c5e7b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mistakes", sa.Column("solid_streak", sa.Integer(), server_default="0", nullable=False))
    op.add_column("mistakes", sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column(
        "mistakes",
        sa.Column(
            "last_solid_lesson_id",
            sa.UUID(),
            sa.ForeignKey("lessons.id", ondelete="SET NULL", name="fk_mistakes_last_solid_lesson_id_lessons"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mistakes", "last_solid_lesson_id")
    op.drop_column("mistakes", "resolved_at")
    op.drop_column("mistakes", "solid_streak")
