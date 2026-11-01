"""The lesson generation background job against real Postgres."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus, LessonStatus
from app.models.job import Job
from app.services.lesson_generation import run_lesson_generation_job
from tests.factories import make_lesson, make_plan, make_profile, make_user
from tests.fake_llm import FakeLLM
from tests.samples import curriculum


async def test_lesson_job_stores_model_dump(db: AsyncSession, fake_llm: FakeLLM, background_sessions: None) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    await make_plan(db, user)
    lesson = await make_lesson(db, user, status=LessonStatus.generating, lesson_number=2, payload={})
    job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.pending)
    db.add(job)
    await db.flush()
    generated = curriculum()
    fake_llm.push(generated)

    await run_lesson_generation_job(job_id=job.id, lesson_id=lesson.id, user_id=user.id)

    db.expire_all()
    await db.refresh(job)
    await db.refresh(lesson)
    dumped = generated.model_dump()
    assert job.status == JobStatus.done
    assert lesson.status == LessonStatus.active
    assert lesson.payload["version"] == 1
    assert lesson.payload["session_summary"] is None
    assert lesson.payload["curriculum"] == dumped
    assert "partner_session" in dumped
    assert dumped["partner_session"] is None
