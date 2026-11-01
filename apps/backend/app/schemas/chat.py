from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.llm import Correction, CourseRoadmap, PracticeResult


class ChatSessionCreateRequest(BaseModel):
    type: Literal["onboarding", "lesson"]
    lesson_id: uuid.UUID | None = None


class ChatSessionResponse(BaseModel):
    id: str
    type: Literal["onboarding", "lesson"]
    lesson_id: str | None = None


class ChatMessageCreateRequest(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    # Raw stored metadata: rows written before TurnMetadata may carry retired keys.
    metadata: dict[str, Any] | None = None


class ChatMessagesListResponse(BaseModel):
    messages: list[ChatMessageOut]


class TurnTiming(BaseModel):
    active_minutes: int
    target_minutes: int


class TurnMetadata(BaseModel):
    """Stored on every assistant message and returned with the turn. Every key is always
    present; each branch sets only what differs from the defaults."""

    corrections: list[Correction] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    plan_updates: dict[str, Any] | None = None
    suggest_finish: bool = False
    course_roadmap_draft: CourseRoadmap | None = None
    practiced: list[PracticeResult] = Field(default_factory=list)
    timing: TurnTiming | None = None


class ChatTurnResponse(BaseModel):
    message_id: str
    content: str
    metadata: TurnMetadata
