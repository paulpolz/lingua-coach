"""Chat session/message request+response shapes and SSE payload models.

Per docs/implementation-readiness.md §6 (REST) and §7 (SSE contract), plus the
plan's coordination rule #3 (`course_roadmap_draft` in `done.metadata`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.roadmap import CourseRoadmap


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
    # Optional structured side-payload persisted on assistant turns
    # (corrections, tips, course_roadmap_draft, …). Null for user turns.
    metadata: dict | None = None


class ChatMessagesListResponse(BaseModel):
    messages: list[ChatMessageOut]


class CorrectionItem(BaseModel):
    span: str
    correction: str
    type: str
    note: str = ""


class PlanUpdates(BaseModel):
    """Partial profile/goal fields per readiness §8 "Plan updates"."""

    goal_summary: str | None = None
    level: str | None = None
    time_budget: dict | None = None
    topics: list[str] | None = None
    vocab_priorities: list[str] | None = None
    target_plan_days: int | None = None
    grammar_mastery: dict[str, int] | None = None


class LessonPlanTask(BaseModel):
    """One item on the pinned lesson checklist (`json:lesson_plan`)."""

    id: str
    label: str
    minutes: int = Field(ge=0)


class LessonPlan(BaseModel):
    tasks: list[LessonPlanTask] = Field(min_length=1)


class TaskUpdate(BaseModel):
    """Coach-confirmed completions for the pinned checklist (`json:task_update`)."""

    completed_task_ids: list[str] = Field(default_factory=list)


class ChatDoneMetadata(BaseModel):
    """`done` event `metadata` — readiness §7 fields + coordination rule #3's
    `course_roadmap_draft` extension (onboarding-mode only; always `null` in
    lesson mode). `lesson_plan` / `task_update` are lesson-mode extras
    (always `null` in onboarding)."""

    corrections: list[CorrectionItem] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    plan_updates: PlanUpdates | None = None
    suggest_finish: bool = False
    course_roadmap_draft: CourseRoadmap | None = None
    lesson_plan: LessonPlan | None = None
    task_update: TaskUpdate | None = None


class LessonMistakeItem(BaseModel):
    """One `mistakes` artifact emitted by the model this turn — see
    skills/exercise_tutor.md "Mistake artifact". `correction` and `lesson_id`
    are optional in the model's write per that doc; the backend always
    stamps `lesson_id` itself and owns `occurrence_count` / `next_review_at`
    (database.md "Upsert rule")."""

    pattern_type: str
    example_text: str
    correction: str | None = None


class LessonTurnExtraction(BaseModel):
    """Structured side-payload the model must emit at the end of every
    lesson-mode turn — see `LESSON_EXTRACTION_CONTRACT` in
    app/services/skills.py. Parsed from the `` ```json:lesson_turn `` fenced
    block by app/services/extraction.py."""

    corrections: list[CorrectionItem] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    plan_updates: PlanUpdates | None = None
    suggest_finish: bool = False
    mistakes: list[LessonMistakeItem] = Field(default_factory=list)


class ChatDoneEvent(BaseModel):
    message_id: str
    content: str
    metadata: ChatDoneMetadata


class ChatErrorEvent(BaseModel):
    code: str
    message: str
