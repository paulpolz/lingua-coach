"""`GET /api/v1/profile` response shape — docs/implementation-readiness.md §6."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TimeBudgetOut(BaseModel):
    minutes_per_session: int
    sessions_per_week: int
    intensity: Literal["light", "moderate", "intensive"]


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
    time_budget: TimeBudgetOut | None
    topics: list[str]
    vocab_priorities: list[str]
    grammar_mastery: dict[str, int]
    schedule: ScheduleOut
