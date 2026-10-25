from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatSessionCreateRequest(BaseModel):
    type: Literal["onboarding", "lesson"]
    lesson_id: str | None = None


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
    metadata: dict | None = None


class ChatMessagesListResponse(BaseModel):
    messages: list[ChatMessageOut]
