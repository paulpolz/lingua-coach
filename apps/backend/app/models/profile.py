import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Profile(Base, TimestampMixin):
    """1:1 with `users` — canonical store for onboarding_interviewer output."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    goal_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_horizon: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_success_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    native_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    level_strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    level_weaknesses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    diagnostic_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    time_budget: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    focus: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    motivation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    interview_completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    grammar_mastery: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    vocabulary_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    target_plan_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_learning_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_plans.id", ondelete="SET NULL"), nullable=True
    )
    projected_completion_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    plan_slip_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pace_window_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
