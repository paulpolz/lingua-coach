from datetime import datetime

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base — import all models before using `Base.metadata`."""


class TimestampMixin:
    """Adds `created_at` / `updated_at` columns with server-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
