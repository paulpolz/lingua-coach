import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import LearningPlanStatus


class LearningPlan(Base, TimestampMixin):
    """Canonical store for the accepted course roadmap (course_composer)."""

    __tablename__ = "learning_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    learning_goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[LearningPlanStatus] = mapped_column(
        SAEnum(LearningPlanStatus, name="learning_plan_status"),
        default=LearningPlanStatus.accepted,
        nullable=False,
    )
    roadmap: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current_milestone_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
