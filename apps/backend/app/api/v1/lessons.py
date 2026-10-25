"""Lesson start, fetch, stop, and finish. Generation runs as a BackgroundTasks job."""

from __future__ import annotations

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
from app.models.enums import ChatMessageRole, ChatSessionType, JobStatus, LearningGoalStatus, LessonStatus, PaceStatus
from app.models.job import Job
from app.models.learning_goal import LearningGoal
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from app.schemas.lesson import FinishLessonRequest, FinishLessonResponse, LessonOut, LessonStartResponse
from app.services.lesson_generation import run_lesson_generation_job
from app.services.llm_usage import check_and_record_user_limit
from app.services.pace import compute_lesson_pace_status, compute_projected_completion
from app.services.report_writer import update_reports_after_lesson

router = APIRouter(prefix="/lessons", tags=["lessons"])


async def _active_lesson(db: AsyncSession, user_id: uuid.UUID) -> Lesson | None:
    return (
        await db.execute(
            select(Lesson).where(
                Lesson.user_id == user_id, Lesson.status.in_((LessonStatus.generating, LessonStatus.active))
            )
        )
    ).scalar_one_or_none()


async def _owned_lesson(db: AsyncSession, lesson_id: str, user_id: uuid.UUID) -> Lesson:
    try:
        lesson = await db.get(Lesson, uuid.UUID(lesson_id))
    except ValueError:
        lesson = None
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


async def _accomplished_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Lesson)
            .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)
        )
        or 0
    )


@router.post("/start", status_code=202, response_model=LessonStartResponse)
async def start_lesson(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonStartResponse:
    existing = await _active_lesson(db, user.id)
    if existing is not None:
        raise APIError(
            409, "An active or generating lesson already exists", "ACTIVE_LESSON_EXISTS",
            active_lesson_id=str(existing.id),
        )
    await check_and_record_user_limit(db, user.id, kind="lesson_start")

    lesson_number = (
        await db.scalar(select(func.coalesce(func.max(Lesson.lesson_number), 0)).where(Lesson.user_id == user.id))
    ) + 1
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
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
    await db.commit()

    background_tasks.add_task(run_lesson_generation_job, job_id=job.id, lesson_id=lesson.id, user_id=user.id)
    return LessonStartResponse(job_id=str(job.id), lesson_id=str(lesson.id), lesson_number=lesson_number)


@router.get("/active", response_model=LessonOut | None)
async def get_active_lesson(
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut | None:
    lesson = await _active_lesson(db, user.id)
    return _lesson_out(lesson) if lesson else None


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: str,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> LessonOut:
    return _lesson_out(await _owned_lesson(db, lesson_id, user.id))


@router.post("/{lesson_id}/stop", status_code=204)
async def stop_lesson(
    lesson_id: str,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Leaving the chat. The lesson stays active and the pace clock keeps running."""
    lesson = await _owned_lesson(db, lesson_id, user.id)
    db.add(ProgressEvent(user_id=user.id, lesson_id=lesson.id, event_type="lesson_chat_stopped"))
    await db.commit()


async def _session_summary(
    db: AsyncSession, lesson: Lesson, session: ChatSession | None, now: datetime, body: FinishLessonRequest | None
) -> dict:
    """Completed slots come from the client if sent; otherwise any `suggest_finish` turn
    means all slots were done; otherwise none were. Missing slots count as 0%."""
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    slot_ids = [s.get("id") for s in curriculum.get("slots") or [] if s.get("id")]

    suggested = False
    if session is not None:
        metadata = (
            await db.execute(
                select(ChatMessage.metadata_json).where(
                    ChatMessage.session_id == session.id, ChatMessage.role == ChatMessageRole.assistant
                )
            )
        ).scalars()
        suggested = any((m or {}).get("suggest_finish") for m in metadata)

    if body and body.completed_slot_ids is not None:
        completed = [s for s in body.completed_slot_ids if s in slot_ids]
    elif suggested:
        completed = list(slot_ids)
    else:
        completed = []
    exit_met = bool(slot_ids) and set(completed) == set(slot_ids)

    new_patterns = (await db.execute(select(Mistake.pattern_type).where(Mistake.lesson_id == lesson.id))).scalars()
    started = lesson.started_at or now
    return {
        "duration_minutes": max(int((now - started).total_seconds() // 60), 0),
        "completed_slots": completed,
        "deferred_items": [
            {"slot_id": s, "reason": "not_completed_before_finish"} for s in slot_ids if s not in completed
        ],
        "exit_criteria_met": exit_met,
        "grammar_focus": curriculum.get("grammar_focus"),
        "new_pattern_types": list(new_patterns),
        "vocab_themes_covered": [curriculum["vocab_theme"]] if curriculum.get("vocab_theme") else [],
        "learner_feedback": body.learner_feedback if body else None,
    }


@router.post("/{lesson_id}/finish", response_model=FinishLessonResponse)
async def finish_lesson(
    lesson_id: str,
    body: FinishLessonRequest | None = None,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> FinishLessonResponse:
    lesson = await _owned_lesson(db, lesson_id, user.id)
    if lesson.status != LessonStatus.active:
        raise APIError(409, f"Lesson is {lesson.status.value}; only an active lesson can be finished", "LESSON_NOT_ACTIVE")

    now = datetime.now(timezone.utc)
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    pace_window = (profile.pace_window_hours if profile else None) or settings.pace_window_hours
    session = (
        await db.execute(
            select(ChatSession).where(ChatSession.type == ChatSessionType.lesson, ChatSession.lesson_id == lesson.id)
        )
    ).scalar_one_or_none()

    pace_status = compute_lesson_pace_status(lesson.started_at, now, pace_window)
    summary = await _session_summary(db, lesson, session, now, body)
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
    schedule_updated = pace_status == PaceStatus.slipped and profile is not None
    if schedule_updated:
        profile.plan_slip_days = (profile.plan_slip_days or 0) + 1
        remaining = (profile.target_plan_days or 0) - await _accomplished_count(db, user.id)
        profile.projected_completion_at = compute_projected_completion(now, remaining, pace_window)
        db.add(
            ProgressEvent(
                user_id=user.id,
                lesson_id=lesson.id,
                event_type="plan_rescheduled",
                payload={"plan_slip_days": profile.plan_slip_days},
            )
        )

    await update_reports_after_lesson(db, user=user, lesson=lesson, session_summary=summary, profile=profile, now=now)

    if session is not None:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.commit()

    return FinishLessonResponse(
        accomplished_at=now, pace_status=pace_status.value, schedule_updated=schedule_updated
    )
