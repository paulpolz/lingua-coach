"""`lesson_record` v1 — canonical `lessons.payload` shape from
docs/tech_requirements/database.md ("payload JSON shape") and
skills/exercise_tutor.md ("Lesson payload"). `LessonCurriculum` is exactly
what the lesson-generation model must produce (validated by
app/services/lesson_generation.py, one repair retry on failure per
ai-api.md); `LessonPayload` is the full persisted `lessons.payload`
envelope. `session_summary` stays `None` until lesson finish (Phase 5).

Also holds the REST response/request shapes for the lesson endpoints —
docs/implementation-readiness.md §6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LessonSlot(BaseModel):
    id: str
    label: str
    exercise_set: str


class InputTask(BaseModel):
    type: Literal["listening", "reading"]
    topic: str
    focus: str


class GoalSpecificTask(BaseModel):
    label: str
    format: str


class LessonCurriculum(BaseModel):
    """Exactly the object the lesson-generation model must return — no
    `version` / `session_summary` wrapper (see `LESSON_GENERATION_CONTRACT`
    in app/services/skills.py)."""

    lesson_goal: str
    grammar_focus: str
    vocab_theme: str
    milestone_index: int = Field(ge=0)
    slots: list[LessonSlot] = Field(min_length=1)
    input_task: InputTask
    goal_specific_task: GoalSpecificTask
    exit_criteria: list[str] = Field(min_length=1)
    partner_session: dict | None = None


class LessonPayload(BaseModel):
    """Full `lessons.payload` envelope persisted once the lesson is `active`."""

    version: int = 1
    curriculum: LessonCurriculum
    session_summary: dict | None = None


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


class DeferredItem(BaseModel):
    slot_id: str
    reason: str


class FocusPatternResult(BaseModel):
    grammar_focus: str
    met: bool
    note: str = ""


class SessionSummary(BaseModel):
    """`lessons.payload.session_summary` — skills/exercise_tutor.md "Session
    summary" shape, written at `POST /lessons/{id}/finish`. See
    `app/api/v1/lessons.py::_build_session_summary` for the derivation
    approach (chat metadata has no other structured signal of "which slots
    did the learner actually finish" in MVP)."""

    duration_minutes: int
    completed_slots: list[str] = Field(default_factory=list)
    deferred_items: list[DeferredItem] = Field(default_factory=list)
    exit_criteria_met: bool
    performance_notes: str = ""
    focus_pattern_result: FocusPatternResult | None = None
    resolved_pattern_types: list[str] = Field(default_factory=list)
    new_pattern_types: list[str] = Field(default_factory=list)
    vocab_themes_covered: list[str] = Field(default_factory=list)
    learner_feedback: str | None = None


class FinishLessonRequest(BaseModel):
    """`POST /lessons/{id}/finish` request body — **not documented** in
    readiness §6 (which shows no request body for this endpoint). Default
    behavior is an empty/no-body POST; this is an **optional MVP extension**
    for the Phase 5 frontend agent, only used if/when the frontend has a
    client-side signal (e.g. explicit per-slot completion UI) better than
    the server's own best-effort derivation from chat metadata. All fields
    optional — omitting the body (or sending `{}`) is fully supported and
    falls back to server-side derivation (see `_build_session_summary`)."""

    completed_slot_ids: list[str] | None = None
    learner_feedback: str | None = None


class FinishLessonResponse(BaseModel):
    status: Literal["accomplished"] = "accomplished"
    accomplished_at: datetime
    pace_status: Literal["on_pace", "slipped"]
    schedule_updated: bool
