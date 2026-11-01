"""Background job from `POST /lessons/start`: one structured Gemini call writes the curriculum.

Runs after the HTTP response is sent, so it opens its own DB session. Context is the
accepted roadmap, profile, last five lesson summaries, and mistakes, never chat history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
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
from app.services.gemini import ChatTurn
from app.services.llm_usage import metered_structured_call
from app.services.prompt_assembly import generation_user_prompt, lesson_generation_system_instruction

logger = logging.getLogger(__name__)


async def run_lesson_generation_job(*, job_id: uuid.UUID, lesson_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lesson = await db.get(Lesson, lesson_id)
        if job is None or lesson is None:
            return
        job.status = JobStatus.running
        await db.commit()

        try:
            curriculum = await _generate(db, user_id=user_id, lesson_number=lesson.lesson_number)
        except Exception as exc:  # noqa: BLE001 - any failure fails the job; the client sees it by polling
            logger.warning("lesson_generation_failed", extra={"job_id": str(job_id), "error": str(exc)})
            job.status = JobStatus.failed
            job.error = str(exc)
            lesson.status = LessonStatus.failed
            await db.commit()
            return

        lesson.payload = {"version": 1, "curriculum": curriculum, "session_summary": None}
        lesson.status = LessonStatus.active
        lesson.started_at = datetime.now(timezone.utc)
        job.status = JobStatus.done
        job.result_ref = str(lesson.id)
        await db.commit()


async def _generate(db: AsyncSession, *, user_id: uuid.UUID, lesson_number: int) -> dict:
    plan = (
        await db.execute(
            select(LearningPlan)
            .where(LearningPlan.user_id == user_id, LearningPlan.status == LearningPlanStatus.accepted)
            .order_by(LearningPlan.accepted_at.desc())
        )
    ).scalars().first()
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one_or_none()
    prior = (
        await db.execute(
            select(Lesson)
            .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)
            .order_by(Lesson.lesson_number.desc())
            .limit(5)
        )
    ).scalars().all()
    mistakes = (
        await db.execute(select(Mistake).where(Mistake.user_id == user_id).order_by(Mistake.last_seen_at.desc()))
    ).scalars().all()

    context = {
        "lesson_number": lesson_number,
        "roadmap": plan.roadmap if plan else None,
        "current_milestone_index": plan.current_milestone_index if plan else 0,
        "learner_profile": {
            column: getattr(profile, column)
            for column in (
                "goal_outcome", "native_language", "target_language", "target_level", "level_strengths",
                "level_weaknesses", "time_budget", "focus", "constraints", "grammar_mastery",
                "vocabulary_summary",
            )
        } if profile else None,
        "prior_lessons": [
            {"lesson_number": p.lesson_number, **{k: (p.payload or {}).get(k) for k in ("curriculum", "session_summary")}}
            for p in prior
        ],
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

    curriculum = await metered_structured_call(
        db,
        user_id,
        "lesson_json",
        model_id=settings.gemini_model_lesson,
        schema=LessonCurriculum,
        system_instruction=system_instruction,
        history=[ChatTurn(role="user", text=prompt)],
    )
    return curriculum.model_dump()
