"""drop quality_events

Revision ID: c2d5e8f1a3b7
Revises: b1e7c4a92f30
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c2d5e8f1a3b7"
down_revision: Union[str, Sequence[str], None] = "b1e7c4a92f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("quality_events")


def downgrade() -> None:
    raise NotImplementedError("quality_events was removed with the ratings feature")
