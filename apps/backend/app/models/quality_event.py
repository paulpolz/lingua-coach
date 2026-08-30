import uuid

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class QualityEvent(Base, TimestampMixin):
    """Online tutor-quality signals (thumbs, CSAT, sampled judge).

    `session_id` and `message_id` are opaque — no FK. Lesson and onboarding
    finish delete chat rows, and thumbs/CSAT must survive that.
    """

    __tablename__ = "quality_events"
    __table_args__ = (
        Index("ix_quality_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_quality_events_kind_message_id", "kind", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
