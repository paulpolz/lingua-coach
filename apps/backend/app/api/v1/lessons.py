"""Lesson start, fetch, stop, and finish. Generation runs as a BackgroundTasks job."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned, require_onboarding_complete
from app.config import settings
from app.core.errors import APIError
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatMessageRole, ChatSessionType, JobStatus, LearningGoalStatus, LessonStatus, PaceStatus
from app.models.job import Job
from app.models.learning_goal import LearningGoal
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from app.schemas.lesson import FinishLessonRequest, FinishLessonResponse, LessonOut, LessonStartResponse
from app.services.lesson_generation import reap_stale_generation, run_lesson_generation_job
from app.services.lesson_timing import TimeBudgetRequired, active_minutes, lesson_target_minutes, target_minutes
from app.services.llm_usage import check_and_record_user_limit
from app.services.pace import compute_lesson_pace_status, compute_projected_completion, pace_window
from app.services.queries import accomplished_count, active_lesson, get_profile
from app.services.report_writer import run_report_update

router = APIRouter(prefix="/lessons", tags=["lessons"])


def _active_lesson_exists(existing: Lesson | None) -> APIError:
    return APIError(
        409,
        "An active or generating lesson already exists",
        "ACTIVE_LESSON_EXISTS",
        active_lesson_id=str(existing.id) if existing else None,
    )


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
    profile = await get_profile(db, user.id)
    try:
        target_minutes(profile)
    except TimeBudgetRequired:
        # Legacy profiles predate the required lesson length; the dashboard asks and PATCHes /profile.
        raise APIError(
            409, "Set how many minutes each lesson should last before starting one.", "TIME_BUDGET_REQUIRED"
        ) from None
    await reap_stale_generation(db, user.id)
    existing = await active_lesson(db, user.id)
    if existing is not None:
        raise _active_lesson_exists(existing)
    await check_and_record_user_limit(db, user.id, kind="lesson_start")

    lesson_number = (
        await db.scalar(select(func.coalesce(func.max(Lesson.lesson_number), 0)).where(Lesson.user_id == user.id)) or 0
    ) + 1
    goal = (
        await db.execute(
            select(LearningGoal).where(
                LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.active
            )
        )
    ).scalar_one_or_none()

    lesson = Lesson(
        user_id=user.id,
        learning_goal_id=goal.id if goal else None,
        learning_plan_id=profile.active_learning_plan_id if profile else None,
        lesson_number=lesson_number,
        payload={},
        status=LessonStatus.generating,
    )
    job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.pending)
    db.add_all([lesson, job])
    user_id = user.id  # rollback expires ORM attributes
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent start won the unique active-lesson index (or the same lesson_number).
        await db.rollback()
        raise _active_lesson_exists(await active_lesson(db, user_id)) from None

    background_tasks.add_task(run_lesson_generation_job, job_id=job.id, lesson_id=lesson.id, user_id=user.id)
    return LessonStartResponse(job_id=str(job.id), lesson_id=str(lesson.id), lesson_number=lesson_number)


@router.get("/active", response_model=LessonOut | None)
async def get_active_lesson(
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut | None:
    lesson = await active_lesson(db, user.id)
    return _lesson_out(lesson) if lesson else None


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: uuid.UUID,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut:
    return _lesson_out(await get_owned(db, Lesson, lesson_id, user, "Lesson"))


@router.post("/{lesson_id}/stop", status_code=204)
async def stop_lesson(
    lesson_id: uuid.UUID,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Leaving the chat. The lesson stays active and the pace clock keeps running."""
    lesson = await get_owned(db, Lesson, lesson_id, user, "Lesson")
    db.add(ProgressEvent(user_id=user.id, lesson_id=lesson.id, event_type="lesson_chat_stopped"))
    await db.commit()


def _final_practice_results(metadata_rows: list[dict | None]) -> dict[str, str]:
    """Last reported result per practiced item across the lesson's turns."""
    final: dict[str, str] = {}
    for metadata in metadata_rows:
        for result in (metadata or {}).get("practiced") or []:
            item = str(result.get("item") or "").strip()
            if item and result.get("result") in ("solid", "shaky"):
                final[item] = result["result"]
    return final


async def _session_summary(
    db: AsyncSession,
    lesson: Lesson,
    session: ChatSession | None,
    profile: Profile | None,
    now: datetime,
    body: FinishLessonRequest | None,
) -> dict:
    """Built by the backend at finish, before the chat rows are deleted; the model never writes it.

    `duration_minutes` is active minutes (idle gaps capped), not wall time. An early finish
    still counts; the shortfall is only recorded.
    """
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    active = 0
    metadata_rows: list[dict | None] = []
    if session is not None:
        active = await active_minutes(db, session.id, settings.lesson_idle_cap_minutes, until=now)
        metadata_rows = list(
            (
                await db.execute(
                    select(ChatMessage.metadata_json).where(
                        ChatMessage.session_id == session.id, ChatMessage.role == ChatMessageRole.assistant
                    )
                )
            ).scalars()
        )
    target = lesson_target_minutes(lesson, profile)
    shortfall = max(target - active, 0) if target else 0
    practice = _final_practice_results(metadata_rows)
    lesson_start = lesson.started_at or lesson.created_at
    # First seen in this lesson; a pattern that only recurred here is not new.
    new_patterns = (
        await db.execute(
            select(Mistake.pattern_type).where(Mistake.lesson_id == lesson.id, Mistake.created_at >= lesson_start)
        )
    ).scalars()
    resolved = (
        await db.execute(
            select(Mistake.pattern_type).where(
                Mistake.user_id == lesson.user_id,
                Mistake.resolved_at >= lesson_start,
            )
        )
    ).scalars()
    return {
        "duration_minutes": active,
        "target_minutes": target,
        "shortfall_minutes": shortfall,
        # Same one-minute tolerance as the suggest_finish guard: 14 of 15 is a full lesson.
        "finished_early": shortfall > 1,
        "grammar_focus": curriculum.get("grammar_focus"),
        "practiced_solid": [item for item, result in practice.items() if result == "solid"],
        "practiced_shaky": [item for item, result in practice.items() if result == "shaky"],
        "resolved_pattern_types": list(resolved),
        "new_pattern_types": list(new_patterns),
        "new_vocabulary": curriculum.get("new_vocabulary") or [],
        "vocab_themes_covered": [curriculum["vocab_theme"]] if curriculum.get("vocab_theme") else [],
        "learner_feedback": body.learner_feedback if body else None,
    }


@router.post("/{lesson_id}/finish", response_model=FinishLessonResponse)
async def finish_lesson(
    lesson_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: FinishLessonRequest | None = None,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> FinishLessonResponse:
    lesson = await get_owned(db, Lesson, lesson_id, user, "Lesson")
    if lesson.status != LessonStatus.active:
        raise APIError(
            409, f"Lesson is {lesson.status.value}; only an active lesson can be finished", "LESSON_NOT_ACTIVE"
        )

    now = datetime.now(UTC)
    profile = await get_profile(db, user.id)
    window = pace_window(profile)
    session = (
        await db.execute(
            select(ChatSession).where(ChatSession.type == ChatSessionType.lesson, ChatSession.lesson_id == lesson.id)
        )
    ).scalar_one_or_none()

    pace_status = compute_lesson_pace_status(lesson.started_at, now, window)
    summary = await _session_summary(db, lesson, session, profile, now, body)
    lesson.payload = {**(lesson.payload or {}), "session_summary": summary}
    lesson.status = LessonStatus.accomplished
    lesson.accomplished_at = now
    lesson.pace_status = pace_status
    await db.flush()
    db.add(
        ProgressEvent(
            user_id=user.id,
            lesson_id=lesson.id,
            event_type="lesson_completed",
            payload={"lesson_number": lesson.lesson_number, "pace_status": pace_status.value},
        )
    )

    # Finishing past the pace window slips the plan by one day.
    schedule_updated = False
    if pace_status == PaceStatus.slipped and profile is not None:
        schedule_updated = True
        profile.plan_slip_days = (profile.plan_slip_days or 0) + 1
        remaining = (profile.target_plan_days or 0) - await accomplished_count(db, user.id)
        profile.projected_completion_at = compute_projected_completion(now, remaining, window)
        db.add(
            ProgressEvent(
                user_id=user.id,
                lesson_id=lesson.id,
                event_type="plan_rescheduled",
                payload={"plan_slip_days": profile.plan_slip_days},
            )
        )

    if session is not None:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.commit()

    # The report LLM call (up to the LLM timeout) runs after the response, in its own
    # session, so finish holds no transaction or connection open while it waits.
    background_tasks.add_task(run_report_update, user_id=user.id, lesson_id=lesson.id, session_summary=summary)

    return FinishLessonResponse(accomplished_at=now, pace_status=pace_status.value, schedule_updated=schedule_updated)
