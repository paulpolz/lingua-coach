"""add native/target language columns; rename english_level to target_level

Revision ID: f4a7b2c91e3d
Revises: e3f9a1c82d4b
Create Date: 2026-08-26 15:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f4a7b2c91e3d"
down_revision: Union[str, Sequence[str], None] = "e3f9a1c82d4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("native_language", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("target_language", sa.Text(), nullable=True))
    op.alter_column(
        "profiles",
        "english_level",
        new_column_name="target_level",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    # Existing rows were English-only product; leave native_language null.
    op.execute(sa.text("UPDATE profiles SET target_language = 'en' WHERE target_language IS NULL"))


def downgrade() -> None:
    op.alter_column(
        "profiles",
        "target_level",
        new_column_name="english_level",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.drop_column("profiles", "target_language")
    op.drop_column("profiles", "native_language")
