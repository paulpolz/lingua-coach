from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScheduleOut(BaseModel):
    target_plan_days: int | None
    plan_days_done: int
    plan_slip_days: int
    projected_completion_at: datetime | None
    pace_window_hours: int
    pace_summary: Literal["on_pace", "behind", "ahead", "not_started"]


class ProfileResponse(BaseModel):
    goal_summary: str | None
    level: str | None
    native_language: str | None = None
    target_language: str | None = None
    time_budget: dict | None
    topics: list
    vocab_priorities: list
    grammar_mastery: dict
    schedule: ScheduleOut


class TimeBudgetUpdate(BaseModel):
    minutes_per_session: int = Field(ge=5, le=180, description="Length of one lesson in minutes.")


class ProfileUpdateRequest(BaseModel):
    """Only the lesson length is editable here; other plan changes go through the coach chat."""

    time_budget: TimeBudgetUpdate
