from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LessonStartResponse(BaseModel):
    job_id: str
    lesson_id: str
    lesson_number: int


class LessonOut(BaseModel):
    id: str
    lesson_number: int
    status: Literal["generating", "active", "accomplished", "failed"]
    started_at: datetime | None
    accomplished_at: datetime | None
    pace_status: Literal["on_pace", "slipped"] | None
    payload: dict


class FinishLessonRequest(BaseModel):
    learner_feedback: str | None = None


class FinishLessonResponse(BaseModel):
    status: Literal["accomplished"] = "accomplished"
    accomplished_at: datetime
    pace_status: Literal["on_pace", "slipped"]
    schedule_updated: bool
