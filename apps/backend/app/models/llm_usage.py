import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LlmUsageEvent(Base, TimestampMixin):
    """One persisted limiter hit.

    Gemini calls use `call_type` `chat`, `lesson_json`, or `report`.
    `lesson_start` is the per-user daily start bucket only — it is not a
    Gemini call and does not count toward RPM, input TPM, or RPD.
    """

    __tablename__ = "llm_usage_events"
    __table_args__ = (
        Index("ix_llm_usage_events_created_at", "created_at"),
        Index(
            "ix_llm_usage_events_user_id_created_at_call_type",
            "user_id",
            "created_at",
            "call_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    call_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
