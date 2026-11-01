from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OnboardingAcceptRequest(BaseModel):
    session_id: str
    course_roadmap: dict


class OnboardingAcceptResponse(BaseModel):
    onboarding_complete: bool
    plan_accepted_at: datetime
