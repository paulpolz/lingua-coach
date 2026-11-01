from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.llm import CourseRoadmap


class OnboardingAcceptRequest(BaseModel):
    session_id: uuid.UUID
    # Validated against the same schema the LLM fills: the client echoes a draft back, and
    # the stored roadmap feeds later prompts, so unknown keys are dropped here.
    course_roadmap: CourseRoadmap


class OnboardingAcceptResponse(BaseModel):
    onboarding_complete: bool
    plan_accepted_at: datetime
