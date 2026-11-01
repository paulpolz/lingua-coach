"""Lesson start / stop / finish through the HTTP API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.config import settings
from app.models.chat import ChatSession
from app.models.enums import JobStatus, LessonStatus
from app.models.job import Job
from app.models.lesson import Lesson
from app.schemas.llm import ReportPatch
from tests.asgi import asgi_post
from tests.conftest import Auth
from tests.factories import make_chat_session, make_lesson, make_messages, make_profile, make_user
from tests.fake_llm import FakeLLM, LLMCall
from tests.samples import curriculum


async def test_concurrent_starts_return_one_202_and_one_409(
    committed_client: httpx.AsyncClient,
    committed_sessions: Callable[[], AsyncSession],
    auth: Auth,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_sessions() as db:
        user = await make_user(db)
        await make_profile(db, user)
        await db.commit()
    fake_llm.push(curriculum(), curriculum())

    # Both requests pass the "no active lesson" check before either inserts.
    barrier = asyncio.Barrier(2)

    async def wait_for_both(*_args: object, **_kwargs: object) -> None:
        await asyncio.wait_for(barrier.wait(), timeout=5)

    monkeypatch.setattr("app.api.v1.lessons.check_and_record_user_limit", wait_for_both)

    results = await asyncio.gather(
        committed_client.post("/api/v1/lessons/start"),
        committed_client.post("/api/v1/lessons/start"),
        return_exceptions=True,
    )
    responses = [r for r in results if isinstance(r, httpx.Response)]
    assert len(responses) == 2, results

    assert sorted(r.status_code for r in responses) == [202, 409], [r.text for r in responses]
    conflict = next(r for r in responses if r.status_code == 409)
    assert conflict.json()["code"] == "ACTIVE_LESSON_EXISTS"
    winner = next(r for r in responses if r.status_code == 202)
    assert conflict.json()["active_lesson_id"] == winner.json()["lesson_id"]
    async with committed_sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Lesson)) == 1


async def test_stale_generating_lesson_does_not_block_start(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    long_ago = datetime.now(UTC) - timedelta(seconds=settings.gemini_timeout_seconds * 2 + 60)
    stuck = await make_lesson(db, user, status=LessonStatus.generating, payload={}, created_at=long_ago)
    stuck_job = Job(user_id=user.id, type="lesson_generate", status=JobStatus.running)
    stuck_job.created_at = long_ago
    db.add(stuck_job)
    await db.flush()
    fake_llm.push(curriculum())

    assert (await client.get("/api/v1/lessons/active")).json() is None
    response = await client.post("/api/v1/lessons/start")

    assert response.status_code == 202, response.text
    stuck_id, job_id = stuck.id, stuck_job.id
    db.expire_all()
    assert (await db.get(Lesson, stuck_id)).status == LessonStatus.failed  # type: ignore[union-attr]
    assert (await db.get(Job, job_id)).status == JobStatus.failed  # type: ignore[union-attr]
    assert response.json()["lesson_number"] == 2


async def test_fresh_generating_lesson_blocks_start(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, status=LessonStatus.generating, payload={})

    response = await client.post("/api/v1/lessons/start")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "An active or generating lesson already exists",
        "code": "ACTIVE_LESSON_EXISTS",
        "active_lesson_id": str(lesson.id),
    }


async def test_finish_returns_before_the_report_llm_call(
    db: AsyncSession, fake_llm: FakeLLM, auth: Auth, background_sessions: None, db_conn: AsyncConnection
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user)
    session = await make_chat_session(db, user, lesson)
    await make_messages(db, session, [0, 2])
    order: list[str] = []

    async def slow_report(_call: LLMCall) -> ReportPatch:
        order.append("report_llm_called")
        await asyncio.sleep(0.2)
        return ReportPatch(ops=[])

    fake_llm.push(slow_report)

    status, body = await asgi_post(f"/api/v1/lessons/{lesson.id}/finish", db_conn, auth, on_response=order.append)

    assert status == 200, body
    assert order == ["response_sent", "report_llm_called"]
    lesson_id, session_id = lesson.id, session.id
    db.expire_all()
    finished = await db.get(Lesson, lesson_id)
    assert finished is not None and finished.status == LessonStatus.accomplished
    assert await db.get(ChatSession, session_id) is None


async def test_report_failure_does_not_undo_finish(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, caplog: pytest.LogCaptureFixture
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user)
    fake_llm.push(RuntimeError("provider down"))

    lesson_id = lesson.id
    with caplog.at_level(logging.WARNING):
        response = await client.post(f"/api/v1/lessons/{lesson_id}/finish", json={})

    assert response.status_code == 200
    assert any(getattr(r, "event", None) == "report_patch_failed" for r in caplog.records)
    db.expire_all()
    assert (await db.get(Lesson, lesson_id)).status == LessonStatus.accomplished  # type: ignore[union-attr]
