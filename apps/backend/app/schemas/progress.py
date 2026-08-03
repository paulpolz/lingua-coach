"""`GET /api/v1/progress` response shape — docs/implementation-readiness.md §6."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ActiveLessonOut(BaseModel):
    id: str
    lesson_number: int
    started_at: datetime | None
    hours_remaining_in_pace_window: float


class ProgressResponse(BaseModel):
    plan_days_done: int
    target_plan_days: int | None
    plan_slip_days: int
    projected_completion_at: datetime | None
    pace_summary: Literal["on_pace", "behind", "ahead", "not_started"]
    active_lesson: ActiveLessonOut | None
