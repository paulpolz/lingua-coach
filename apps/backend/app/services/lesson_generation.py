"""Background job from `POST /lessons/start`: one structured Gemini call writes the curriculum.

Runs after the HTTP response is sent, so it opens its own DB session. Context is the
accepted roadmap, profile, last five lesson summaries, and mistakes, never chat history.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.enums import JobStatus, LearningPlanStatus, LessonStatus
from app.models.job import Job
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.schemas.llm import LessonCurriculum
from app.services.gemini import ChatTurn, GeminiError, public_detail
from app.services.lesson_timing import target_minutes
from app.services.llm_usage import metered_structured_call
from app.services.memory import (
    CONDENSED_PRIOR_LESSONS,
    FULL_PRIOR_LESSONS,
    GENERATION_MISTAKES,
    prior_lesson_line,
    rank_mistakes,
)
from app.services.prompt_assembly import (
    generation_user_prompt,
    lesson_generation_system_instruction,
    log_context_tokens,
)

logger = logging.getLogger(__name__)


def stale_generation_cutoff() -> datetime:
    """A `generating` lesson older than this lost its job (the job runs in the web process)."""
    return datetime.now(UTC) - timedelta(seconds=settings.gemini_timeout_seconds * 2)


_STALE_JOB_ERROR = "Lesson generation did not finish. Please start a new lesson."


async def reap_stale_generation(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Fail lessons and jobs left `generating`/`running` by a deploy or crash mid-generation.

    Flushes only; the caller's commit makes it durable.
    """
    cutoff = stale_generation_cutoff()
    await db.execute(
        update(Lesson)
        .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.generating, Lesson.created_at < cutoff)
        .values(status=LessonStatus.failed)
    )
    await db.execute(
        update(Job)
        .where(
            Job.user_id == user_id,
            Job.type == "lesson_generate",
            Job.status.in_((JobStatus.pending, JobStatus.running)),
            Job.created_at < cutoff,
        )
        .values(status=JobStatus.failed, error=_STALE_JOB_ERROR)
    )


async def run_lesson_generation_job(*, job_id: uuid.UUID, lesson_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lesson = await db.get(Lesson, lesson_id)
        if job is None or lesson is None:
            return
        job.status = JobStatus.running
        await db.commit()

        try:
            curriculum, minutes = await _generate(db, user_id=user_id, lesson_number=lesson.lesson_number)
        except Exception as exc:  # noqa: BLE001 - any failure fails the job; the client sees it by polling
            logger.warning("lesson_generation_failed", extra={"job_id": str(job_id), "error": str(exc)[:500]})
            job.status = JobStatus.failed
            # `job.error` is returned by GET /jobs/{id}; keep provider text out of it.
            job.error = public_detail(exc.code) if isinstance(exc, GeminiError) else "Lesson generation failed."
            lesson.status = LessonStatus.failed
            await db.commit()
            return

        # target_minutes is copied here so a mid-lesson plan change does not move the goal.
        lesson.payload = {"version": 1, "curriculum": curriculum, "session_summary": None, "target_minutes": minutes}
        lesson.status = LessonStatus.active
        lesson.started_at = datetime.now(UTC)
        job.status = JobStatus.done
        job.result_ref = str(lesson.id)
        await db.commit()


def _plan_focus(plan: LearningPlan | None) -> str:
    """Focus words for mistake ranking: the current milestone and block theme."""
    roadmap = (plan.roadmap if plan else None) or {}
    index = plan.current_milestone_index if plan else 0
    milestone: dict = next((m for m in roadmap.get("milestones") or [] if m.get("index") == index), {})
    block = roadmap.get("current_block") or {}
    parts = (milestone.get("title"), milestone.get("skill_developed"), block.get("focus_summary"))
    return " ".join(str(part) for part in parts if part)


async def _generate(db: AsyncSession, *, user_id: uuid.UUID, lesson_number: int) -> tuple[dict, int]:
    plan = (
        (
            await db.execute(
                select(LearningPlan)
                .where(LearningPlan.user_id == user_id, LearningPlan.status == LearningPlanStatus.accepted)
                .order_by(LearningPlan.accepted_at.desc())
            )
        )
        .scalars()
        .first()
    )
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one_or_none()
    prior = (
        (
            await db.execute(
                select(Lesson)
                .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)
                .order_by(Lesson.lesson_number.desc())
                .limit(FULL_PRIOR_LESSONS + CONDENSED_PRIOR_LESSONS)
            )
        )
        .scalars()
        .all()
    )
    open_mistakes = (
        (await db.execute(select(Mistake).where(Mistake.user_id == user_id, Mistake.resolved_at.is_(None))))
        .scalars()
        .all()
    )
    mistakes = rank_mistakes(open_mistakes, _plan_focus(plan), datetime.now(UTC), k=GENERATION_MISTAKES)

    minutes = target_minutes(profile)
    context = {
        "lesson_number": lesson_number,
        "target_minutes": minutes,
        "roadmap": plan.roadmap if plan else None,
        "current_milestone_index": plan.current_milestone_index if plan else 0,
        "learner_profile": {
            column: getattr(profile, column)
            for column in (
                "goal_outcome",
                "native_language",
                "target_language",
                "target_level",
                "level_strengths",
                "level_weaknesses",
                "time_budget",
                "focus",
                "constraints",
                "grammar_mastery",
                "vocabulary_summary",
            )
        }
        if profile
        else None,
        "prior_lessons": [
            {
                "lesson_number": p.lesson_number,
                **{k: (p.payload or {}).get(k) for k in ("curriculum", "session_summary")},
            }
            for p in prior[:FULL_PRIOR_LESSONS]
        ],
        "earlier_lessons": [prior_lesson_line(p) for p in prior[FULL_PRIOR_LESSONS:]],
        "open_mistakes": [
            {
                "pattern_type": m.pattern_type,
                "example_text": m.example_text,
                "correction": m.correction,
                "occurrence_count": m.occurrence_count,
                "next_review_at": m.next_review_at,
            }
            for m in mistakes
        ],
    }
    system_instruction = lesson_generation_system_instruction(
        profile.native_language if profile else None, profile.target_language if profile else None
    )
    prompt = generation_user_prompt(context)
    log_context_tokens("lesson_json", {key: json.dumps(value, default=str) for key, value in context.items()})

    curriculum = await metered_structured_call(
        db,
        user_id,
        "lesson_json",
        model_id=settings.gemini_model_lesson,
        schema=LessonCurriculum,
        system_instruction=system_instruction,
        history=[ChatTurn(role="user", text=prompt)],
        trace_metadata={"lesson_number": lesson_number},
    )
    return curriculum.model_dump(), minutes
