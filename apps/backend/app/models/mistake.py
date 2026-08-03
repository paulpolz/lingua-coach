import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Mistake(Base, TimestampMixin):
    """Canonical store for recurring error patterns (exercise_tutor)."""

    __tablename__ = "mistakes"
    __table_args__ = (Index("ix_mistakes_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    pattern_type: Mapped[str] = mapped_column(String(255), nullable=False)
    example_text: Mapped[str] = mapped_column(Text, nullable=False)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_review_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
