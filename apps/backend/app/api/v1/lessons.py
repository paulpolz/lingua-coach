"""Lesson generation + fetch — docs/implementation-readiness.md §6.

`POST /lessons/start` inserts the `lessons` + `jobs` rows synchronously (so
the 202 response's `job_id`/`lesson_id`/`lesson_number` are always
consistent with the DB) and schedules the actual generation as a
`BackgroundTasks` callback (app/services/lesson_generation.py) — no
Redis/Celery per backend.md. `GET /jobs/{job_id}` lives in
app/api/v1/jobs.py since it is not lesson-scoped.

All routes here depend on `require_onboarding_complete` (403 gate).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarding_complete
from app.config import settings
from app.core.errors import APIError
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import (
    ChatMessageRole,
    ChatSessionType,
    JobStatus,
    LearningGoalStatus,
    LessonStatus,
    PaceStatus,
)
from app.models.job import Job
from app.models.learning_goal import LearningGoal
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from app.schemas.lesson import (
    DeferredItem,
    FinishLessonRequest,
    FinishLessonResponse,
    FocusPatternResult,
    LessonOut,
    LessonStartResponse,
    SessionSummary,
)
from app.services.lesson_generation import run_lesson_generation_job
from app.services.pace import compute_lesson_pace_status, compute_projected_completion
from app.services.rate_limit import check_and_record
from app.services.report_writer import update_reports_after_lesson

router = APIRouter(prefix="/lessons", tags=["lessons"])

_ACTIVE_LESSON_STATUSES = (LessonStatus.generating, LessonStatus.active)
_LESSON_START_WINDOW_SECONDS = 86400.0


async def _get_active_lesson(db: AsyncSession, user_id: uuid.UUID) -> Lesson | None:
    result = await db.execute(
        select(Lesson).where(Lesson.user_id == user_id, Lesson.status.in_(_ACTIVE_LESSON_STATUSES))
    )
    return result.scalar_one_or_none()


async def _get_owned_lesson(db: AsyncSession, lesson_id: str, user_id: uuid.UUID) -> Lesson:
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise APIError(404, "Lesson not found", "NOT_FOUND") from None
    lesson = await db.get(Lesson, lesson_uuid)
    if lesson is None or lesson.user_id != user_id:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    return lesson


def _lesson_out(lesson: Lesson) -> LessonOut:
    return LessonOut(
        id=str(lesson.id),
        lesson_number=lesson.lesson_number,
        status=lesson.status.value,
        started_at=lesson.started_at,
        accomplished_at=lesson.accomplished_at,
        pace_status=lesson.pace_status.value if lesson.pace_status else None,
        payload=lesson.payload or {},
    )


@router.post("/start", status_code=202, response_model=LessonStartResponse)
async def start_lesson(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonStartResponse:
    # database.md "Lesson sequencing rules": at most one generating/active
    # lesson per user — reject before touching rate limit or sequencing.
    existing = await _get_active_lesson(db, user.id)
    if existing is not None:
        raise APIError(
            409,
            "An active or generating lesson already exists",
            "ACTIVE_LESSON_EXISTS",
            active_lesson_id=str(existing.id),
        )

    if not check_and_record(
        f"lesson_start:{user.id}",
        settings.lesson_start_rate_limit_per_day,
        window_seconds=_LESSON_START_WINDOW_SECONDS,
    ):
        raise APIError(429, "Lesson start rate limit exceeded", "RATE_LIMIT_EXCEEDED")

    lesson_number = (
        await db.scalar(
            select(func.coalesce(func.max(Lesson.lesson_number), 0)).where(Lesson.user_id == user.id)
        )
    ) + 1

    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()

    goal_result = await db.execute(
        select(LearningGoal).where(
            LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.active
        )
    )
    goal = goal_result.scalar_one_or_none()

    lesson = Lesson(
        user_id=user.id,
        learning_goal_id=goal.id if goal else None,
        learning_plan_id=profile.active_learning_plan_id if profile else None,
        lesson_number=lesson_number,
        payload={},
        status=LessonStatus.generating,
    )
    db.add(lesson)
    await db.flush()

    job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.pending, result_ref=None)
    db.add(job)
    await db.flush()

    job_id, lesson_id = job.id, lesson.id
    await db.commit()

    background_tasks.add_task(run_lesson_generation_job, job_id=job_id, lesson_id=lesson_id, user_id=user.id)

    return LessonStartResponse(job_id=str(job_id), lesson_id=str(lesson_id), lesson_number=lesson_number)


@router.get("/active", response_model=LessonOut | None)
async def get_active_lesson(
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut | None:
    lesson = await _get_active_lesson(db, user.id)
    return _lesson_out(lesson) if lesson is not None else None


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: str,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    return _lesson_out(lesson)


@router.post("/{lesson_id}/stop", status_code=204)
async def stop_lesson(
    lesson_id: str,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> None:
    """backend.md "Lesson lifecycle" — Stop vs finish: stopping is a
    UI-convenience "leave chat" signal only. The lesson stays `active`
    (resumable via the existing lesson + chat session) and the 24h pace
    clock keeps running; there is no required status change or DB write.
    We log an optional `progress_events` row purely for local debugging
    visibility into stop/resume patterns — safe to remove without changing
    behavior.
    """
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    db.add(
        ProgressEvent(
            user_id=user.id,
            lesson_id=lesson.id,
            event_type="lesson_chat_stopped",
            payload=None,
        )
    )
    await db.commit()
    return None


async def _get_lesson_chat_session(db: AsyncSession, lesson_id: uuid.UUID) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.type == ChatSessionType.lesson, ChatSession.lesson_id == lesson_id
        )
    )
    return result.scalar_one_or_none()


async def _lesson_chat_suggested_finish(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """`suggest_finish` signal (readiness §7 `done.metadata`) is only ever
    persisted onto `chat_messages.metadata` — there is no dedicated column —
    so scan this lesson's assistant messages for the flag having been set on
    *any* turn (skills/exercise_tutor.md: once all curriculum slots are done
    the tutor sets it and keeps the session open until the explicit Finish
    action, so a `True` seen earlier in the session still means "all planned
    exercises were done" at finish time)."""
    result = await db.execute(
        select(ChatMessage.metadata_json).where(
            ChatMessage.session_id == session_id, ChatMessage.role == ChatMessageRole.assistant
        )
    )
    return any((metadata or {}).get("suggest_finish") for metadata in result.scalars().all())


async def _build_session_summary(
    db: AsyncSession,
    *,
    lesson: Lesson,
    now: datetime,
    request_body: FinishLessonRequest | None,
) -> SessionSummary:
    """Derive `session_summary` server-side (readiness §6 / the task brief:
    the endpoint takes no *required* request body).

    **Derivation approach (documented per the task brief since the docs
    leave this underspecified):**

    1. If the frontend passed `completed_slot_ids` in an (optional) request
       body, treat that as authoritative — it reflects whatever the client
       observed directly. `exit_criteria_met` is then true iff every
       curriculum slot was reported completed.
    2. Otherwise, fall back to the chat signal already computed during
       Phase 4: if *any* assistant turn in this lesson's chat set
       `suggest_finish: true`, all curriculum slots are considered
       completed (the tutor only sets that flag once every planned
       exercise is done) and `exit_criteria_met = true`.
    3. Otherwise (early finish, no `suggest_finish` ever seen, no explicit
       client report) — the simplest robust MVP default: `completed_slots`
       is empty and `exit_criteria_met = false`. Per skills/exercise_tutor.md
       "Completion and exit criteria", incomplete slots count as 0% anyway,
       so an empty list is a safe, conservative default rather than
       guessing partial credit from chat content.

    Slots not in `completed_slots` become `deferred_items` (reason
    `"not_completed_before_finish"`). `new_pattern_types` reads the
    `mistakes` rows already upserted for this lesson during chat (Phase 4);
    `resolved_pattern_types` has no dedicated signal in MVP chat metadata so
    is left empty (documented anti-pattern to avoid: guessing resolution
    from chat text).
    """
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    slot_ids = [s.get("id") for s in curriculum.get("slots") or [] if s.get("id")]

    session = await _get_lesson_chat_session(db, lesson.id)
    suggest_finish_seen = (
        await _lesson_chat_suggested_finish(db, session.id) if session is not None else False
    )

    if request_body is not None and request_body.completed_slot_ids is not None:
        completed_slots = [s for s in request_body.completed_slot_ids if s in slot_ids]
        exit_criteria_met = bool(slot_ids) and set(completed_slots) == set(slot_ids)
    elif suggest_finish_seen:
        completed_slots = list(slot_ids)
        exit_criteria_met = True
    else:
        completed_slots = []
        exit_criteria_met = False

    deferred_items = [
        DeferredItem(slot_id=slot_id, reason="not_completed_before_finish")
        for slot_id in slot_ids
        if slot_id not in completed_slots
    ]

    duration_minutes = 0
    if lesson.started_at is not None:
        duration_minutes = max(int((now - lesson.started_at).total_seconds() // 60), 0)

    mistakes_result = await db.execute(select(Mistake.pattern_type).where(Mistake.lesson_id == lesson.id))
    new_pattern_types = list(mistakes_result.scalars().all())

    grammar_focus = curriculum.get("grammar_focus")
    focus_pattern_result = (
        FocusPatternResult(grammar_focus=grammar_focus, met=exit_criteria_met, note="")
        if grammar_focus
        else None
    )

    vocab_theme = curriculum.get("vocab_theme")
    learner_feedback = request_body.learner_feedback if request_body is not None else None

    return SessionSummary(
        duration_minutes=duration_minutes,
        completed_slots=completed_slots,
        deferred_items=deferred_items,
        exit_criteria_met=exit_criteria_met,
        performance_notes="",
        focus_pattern_result=focus_pattern_result,
        resolved_pattern_types=[],
        new_pattern_types=new_pattern_types,
        vocab_themes_covered=[vocab_theme] if vocab_theme else [],
        learner_feedback=learner_feedback,
    )


@router.post("/{lesson_id}/finish", response_model=FinishLessonResponse)
async def finish_lesson(
    lesson_id: str,
    body: FinishLessonRequest | None = None,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> FinishLessonResponse:
    """backend.md "Lesson lifecycle": explicit Finish action → `accomplished`;
    pace evaluated; schedule maybe rescheduled; lesson chat deleted. No
    request body is required (readiness §6 documents none) — `body` is an
    optional Phase-5 frontend extension, see `FinishLessonRequest`.
    """
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    if lesson.status != LessonStatus.active:
        raise APIError(
            409,
            f"Lesson is {lesson.status.value}; only an active lesson can be finished",
            "LESSON_NOT_ACTIVE",
        )

    now = datetime.now(timezone.utc)
    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()
    pace_window_hours = (profile.pace_window_hours if profile else None) or settings.pace_window_hours

    pace_status = compute_lesson_pace_status(lesson.started_at, now, pace_window_hours)
    session_summary = await _build_session_summary(db, lesson=lesson, now=now, request_body=body)

    # database.md "payload JSON shape": merge `session_summary` in, keep
    # `curriculum` (and `version`) untouched.
    payload = dict(lesson.payload or {})
    payload["session_summary"] = json.loads(session_summary.model_dump_json())
    lesson.payload = payload
    lesson.status = LessonStatus.accomplished
    lesson.accomplished_at = now
    lesson.pace_status = pace_status
    # Flush so the plan_days_done count below (if a slip reschedule is
    # needed) already reflects this lesson's new `accomplished` status.
    await db.flush()

    db.add(
        ProgressEvent(
            user_id=user.id,
            lesson_id=lesson.id,
            event_type="lesson_completed",
            payload={
                "lesson_number": lesson.lesson_number,
                "pace_status": pace_status.value,
                "duration_minutes": session_summary.duration_minutes,
            },
        )
    )

    schedule_updated = False
    if pace_status == PaceStatus.slipped and profile is not None:
        # backend.md "Plan schedule and pacing": slip -> +1 `plan_slip_days`,
        # recompute `projected_completion_at`, emit `plan_rescheduled`.
        profile.plan_slip_days = (profile.plan_slip_days or 0) + 1

        plan_days_done = (
            await db.scalar(
                select(func.count())
                .select_from(Lesson)
                .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
            )
            or 0
        )
        remaining_plan_days = (profile.target_plan_days or 0) - plan_days_done
        profile.projected_completion_at = compute_projected_completion(
            now, remaining_plan_days, pace_window_hours
        )
        db.add(
            ProgressEvent(
                user_id=user.id,
                lesson_id=lesson.id,
                event_type="plan_rescheduled",
                payload={
                    "plan_slip_days": profile.plan_slip_days,
                    "projected_completion_at": profile.projected_completion_at.isoformat(),
                },
            )
        )
        schedule_updated = True

    await update_reports_after_lesson(
        db,
        user=user,
        lesson=lesson,
        session_summary=session_summary,
        profile=profile,
        now=now,
    )

    # Retention (database.md "Lesson data flow" / "Chat" retention rules):
    # delete this lesson's chat transcript + session on finish — mirrors
    # onboarding/accept's deletion pattern exactly.
    session = await _get_lesson_chat_session(db, lesson.id)
    if session is not None:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session.id))

    await db.commit()

    return FinishLessonResponse(
        status="accomplished",
        accomplished_at=now,
        pace_status=pace_status.value,
        schedule_updated=schedule_updated,
    )
