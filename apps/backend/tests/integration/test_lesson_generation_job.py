"""The lesson generation background job against real Postgres."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus, LessonStatus
from app.models.job import Job
from app.services.lesson_generation import run_lesson_generation_job
from tests.factories import make_lesson, make_mistake, make_plan, make_profile, make_user
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


async def test_failed_job_stores_a_generic_error(
    db: AsyncSession, fake_llm: FakeLLM, background_sessions: None
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, status=LessonStatus.generating, payload={})
    job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.pending)
    db.add(job)
    await db.flush()
    fake_llm.push(RuntimeError("provider said key=AIza-secret"))

    await run_lesson_generation_job(job_id=job.id, lesson_id=lesson.id, user_id=user.id)

    db.expire_all()
    await db.refresh(job)
    await db.refresh(lesson)
    assert job.status == JobStatus.failed
    assert lesson.status == LessonStatus.failed
    assert job.error is not None and "secret" not in job.error


async def test_generation_context_is_budgeted(db: AsyncSession, fake_llm: FakeLLM, background_sessions: None) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    await make_plan(db, user)
    for n in range(1, 7):
        summary = {"duration_minutes": 15}
        payload = {
            "curriculum": {"grammar_focus": f"grammar-{n}", "vocab_theme": f"theme-{n}"},
            "session_summary": summary,
        }
        await make_lesson(db, user, status=LessonStatus.accomplished, lesson_number=n, payload=payload)
    for i in range(20):
        await make_mistake(db, user, f"pattern-{i:02d}", occurrence_count=1 + i % 5)
    lesson = await make_lesson(db, user, status=LessonStatus.generating, lesson_number=7, payload={})
    job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.pending)
    db.add(job)
    await db.flush()
    fake_llm.push(curriculum())

    await run_lesson_generation_job(job_id=job.id, lesson_id=lesson.id, user_id=user.id)

    prompt = fake_llm.calls[-1].text
    assert prompt.count('"grammar_focus": "grammar-') == 2  # lessons 6 and 5 in full
    assert 'Lesson 4: grammar \\"grammar-4\\"' in prompt and "Lesson 2: grammar" in prompt
    assert "grammar-1" not in prompt
    assert prompt.count('"pattern_type": "pattern-') == 15
