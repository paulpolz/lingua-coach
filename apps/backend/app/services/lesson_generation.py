"""In-process lesson generation job (backend.md "Async model -> Lesson
generation"; database.md "Lesson data flow"). Runs as a FastAPI
`BackgroundTasks` callback scheduled from `POST /lessons/start`
(app/api/v1/lessons.py) — it executes *after* that request's response is
sent, so it opens its own DB session rather than reusing the request-scoped
one.

Generation context (ai-api.md "Structured lesson output" + "Request
lifecycle"; exercise_tutor.md "Inputs"): active `learning_plans.roadmap`,
`profiles`, last N=5 accomplished `lessons` (`payload.curriculum` +
`payload.session_summary` only — never chat history), and open `mistakes`.

Validation lives in the lesson graph: one repair retry on invalid JSON /
schema failure, then fail the job + lesson with a clear `error` message.
A `GeminiError` (timeout/upstream failure) is not retried — it fails the
job immediately, same as `stream_chat` failures do for chat.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.enums import JobStatus, LearningPlanStatus, LessonStatus
from app.models.job import Job
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.services.lesson_graph import (
    LessonGenerationError as LessonGenerationError,
    invoke_lesson_graph,
)
from app.services.prompt_assembly import (
    build_generation_user_prompt,
    lesson_generation_system_instruction,
)

logger = logging.getLogger(__name__)

_PRIOR_LESSONS_LIMIT = 5


async def run_lesson_generation_job(*, job_id: uuid.UUID, lesson_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Job body: `pending` -> `running` -> `done` | `failed`.

    Never raises — any failure (context error, invalid JSON after repair
    retry, Gemini timeout/error) is caught and persisted onto `jobs.error` /
    `lessons.status = failed` so the client sees it via polling, per
    backend.md's lesson lifecycle table ("Job failure ... not learner
    failure; no special MVP screen").
    """
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lesson = await db.get(Lesson, lesson_id)
        if job is None or lesson is None:
            logger.error(
                "lesson_generation job=%s lesson=%s: row missing at job start", job_id, lesson_id
            )
            return

        job.status = JobStatus.running
        await db.commit()

        try:
            prompt, native, target = await _build_generation_prompt(
                db, user_id=user_id, lesson_number=lesson.lesson_number
            )
            state = await invoke_lesson_graph(
                prompt=prompt,
                system_instruction=lesson_generation_system_instruction(native, target),
                db=db,
                user_id=user_id,
                job_id=job_id,
                lesson_id=lesson_id,
            )
            curriculum = state["curriculum"]
        except Exception as exc:  # noqa: BLE001 - normalize any failure into a failed job/lesson
            logger.warning(
                "lesson_generation failed: %s",
                exc,
                extra={
                    "event": "lesson_generation_failed",
                    "job_id": str(job_id),
                    "lesson_id": str(lesson_id),
                    "user_id": str(user_id),
                    "request_id": str(job_id),
                },
            )
            job.status = JobStatus.failed
            job.error = str(exc)
            lesson.status = LessonStatus.failed
            await db.commit()
            return

        lesson.payload = {
            "version": 1,
            "curriculum": curriculum.model_dump(),
            "session_summary": None,
        }
        lesson.status = LessonStatus.active
        lesson.started_at = datetime.now(timezone.utc)
        job.status = JobStatus.done
        job.result_ref = str(lesson.id)
        await db.commit()


async def _build_generation_prompt(
    db: AsyncSession, *, user_id: uuid.UUID, lesson_number: int
) -> tuple[str, str | None, str | None]:
    """Gather generation context and render it as a single prompt turn.

    Gemini is stateless (ai-api.md "Request lifecycle") — every field the
    model needs must be injected here; there is no session memory to rely on.
    """
    plan_result = await db.execute(
        select(LearningPlan)
        .where(LearningPlan.user_id == user_id, LearningPlan.status == LearningPlanStatus.accepted)
        .order_by(LearningPlan.accepted_at.desc())
    )
    plan = plan_result.scalars().first()

    profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    prior_lessons_result = await db.execute(
        select(Lesson)
        .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)
        .order_by(Lesson.lesson_number.desc())
        .limit(_PRIOR_LESSONS_LIMIT)
    )
    prior_lessons = prior_lessons_result.scalars().all()

    mistakes_result = await db.execute(
        select(Mistake).where(Mistake.user_id == user_id).order_by(Mistake.last_seen_at.desc())
    )
    mistakes = mistakes_result.scalars().all()

    context = {
        "lesson_number": lesson_number,
        "active_plan": {
            "roadmap": plan.roadmap if plan else None,
            "current_milestone_index": plan.current_milestone_index if plan else 0,
        },
        "learner_profile": _profile_snapshot(profile),
        # database.md: inject only `payload.curriculum` + `payload.session_summary`
        # from prior lessons — never full chat transcripts.
        "prior_lessons": [
            {
                "lesson_number": prior.lesson_number,
                "curriculum": (prior.payload or {}).get("curriculum"),
                "session_summary": (prior.payload or {}).get("session_summary"),
            }
            for prior in prior_lessons
        ],
        "open_mistakes": [
            {
                "pattern_type": m.pattern_type,
                "example_text": m.example_text,
                "correction": m.correction,
                "occurrence_count": m.occurrence_count,
                "next_review_at": m.next_review_at.isoformat() if m.next_review_at else None,
            }
            for m in mistakes
        ],
    }

    prompt = build_generation_user_prompt(context)
    native = profile.native_language if profile else None
    target = profile.target_language if profile else None
    return prompt, native, target


def _profile_snapshot(profile: Profile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "goal_outcome": profile.goal_outcome,
        "native_language": profile.native_language,
        "target_language": profile.target_language,
        "target_level": profile.target_level,
        "level_strengths": profile.level_strengths,
        "level_weaknesses": profile.level_weaknesses,
        "time_budget": profile.time_budget,
        "focus": profile.focus,
        "constraints": profile.constraints,
        "grammar_mastery": profile.grammar_mastery,
        "vocabulary_summary": profile.vocabulary_summary,
    }
