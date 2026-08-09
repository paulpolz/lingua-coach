import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ChatMessageRole, ChatSessionType


class ChatSession(Base, TimestampMixin):
    """One session per onboarding, one per lesson. Deleted on accept/finish."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index(
            "uq_chat_sessions_one_onboarding_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("type = 'onboarding'"),
        ),
        Index(
            "uq_chat_sessions_one_lesson_per_user_lesson",
            "user_id",
            "lesson_id",
            unique=True,
            postgresql_where=text("type = 'lesson' AND lesson_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[ChatSessionType] = mapped_column(
        SAEnum(ChatSessionType, name="chat_session_type"), nullable=False
    )


class ChatMessage(Base, TimestampMixin):
    """Live transcript for UI resume — deleted after onboarding accept / lesson finish."""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatMessageRole] = mapped_column(
        SAEnum(ChatMessageRole, name="chat_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Python attribute is `metadata_json` because `metadata` is reserved by
    # the declarative Base; the underlying DB column is still named `metadata`.
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
