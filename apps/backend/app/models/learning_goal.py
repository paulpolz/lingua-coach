import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import LearningGoalStatus


class LearningGoal(Base, TimestampMixin):
    __tablename__ = "learning_goals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    goal_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    horizon: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[LearningGoalStatus] = mapped_column(
        SAEnum(LearningGoalStatus, name="learning_goal_status"),
        default=LearningGoalStatus.draft,
        nullable=False,
    )
