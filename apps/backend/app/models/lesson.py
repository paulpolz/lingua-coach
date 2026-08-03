import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import LessonStatus, PaceStatus


class Lesson(Base, TimestampMixin):
    """Canonical store for lesson curriculum + session outcome (exercise_tutor)."""

    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_number", name="uq_lessons_user_id_lesson_number"),
        Index(
            "ix_lessons_user_id_active",
            "user_id",
            postgresql_where=text("status IN ('generating', 'active')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    learning_goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_goals.id", ondelete="SET NULL"), nullable=True
    )
    learning_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_plans.id", ondelete="SET NULL"), nullable=True
    )

    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[LessonStatus] = mapped_column(
        SAEnum(LessonStatus, name="lesson_status"), default=LessonStatus.generating, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    accomplished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    pace_status: Mapped[PaceStatus | None] = mapped_column(
        SAEnum(PaceStatus, name="pace_status"), nullable=True
    )
