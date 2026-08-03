"""`POST /api/v1/onboarding/accept` — docs/implementation-readiness.md §6."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.roadmap import CourseRoadmap


class OnboardingAcceptRequest(BaseModel):
    session_id: str
    course_roadmap: CourseRoadmap


class OnboardingAcceptResponse(BaseModel):
    onboarding_complete: bool
    plan_accepted_at: datetime
