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
from tests.factories import make_chat_session, make_lesson, make_messages, make_mistake, make_profile, make_user
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
    long_ago = datetime.now(UTC) - timedelta(seconds=settings.llm_timeout_seconds * 2 + 60)
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


async def test_early_finish_counts_and_records_the_shortfall(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user, minutes_per_session=15)
    payload = {
        "version": 1,
        "curriculum": {"grammar_focus": "past simple", "vocab_theme": "travel", "new_vocabulary": ["luggage", "gate"]},
        "target_minutes": 15,
        "session_summary": None,
    }
    lesson = await make_lesson(db, user, payload=payload)
    session = await make_chat_session(db, user, lesson)
    messages = await make_messages(db, session, [0, 2, 4, 8])  # user, assistant, user, assistant
    messages[1].metadata_json = {
        "practiced": [
            {"aspect": "grammar", "item": "past simple", "result": "shaky"},
            {"aspect": "vocabulary", "item": "gate", "result": "solid"},
        ]
    }
    messages[3].metadata_json = {"practiced": [{"aspect": "grammar", "item": "past simple", "result": "solid"}]}
    await make_mistake(db, user, "articles", resolved_at=datetime.now(UTC), next_review_at=None)
    long_ago = datetime.now(UTC) - timedelta(days=30)
    await make_mistake(db, user, "word order", lesson_id=lesson.id, occurrence_count=3, created_at=long_ago)
    await make_mistake(db, user, "past simple", lesson_id=lesson.id, created_at=datetime.now(UTC))
    lesson.started_at = datetime.now(UTC) - timedelta(minutes=20)
    await db.flush()
    lesson_id = lesson.id
    fake_llm.push(ReportPatch(ops=[]))

    response = await client.post(f"/api/v1/lessons/{lesson_id}/finish", json={"learner_feedback": "More emails"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accomplished"
    db.expire_all()
    done = await db.get(Lesson, lesson_id)
    assert done is not None and done.status == LessonStatus.accomplished
    summary = done.payload["session_summary"]
    assert summary["duration_minutes"] == 8
    assert summary["target_minutes"] == 15
    assert summary["shortfall_minutes"] == 7
    assert summary["finished_early"] is True
    assert sorted(summary["practiced_solid"]) == ["gate", "past simple"]
    assert summary["practiced_shaky"] == []
    assert summary["resolved_pattern_types"] == ["articles"]
    assert summary["new_vocabulary"] == ["luggage", "gate"]
    assert summary["learner_feedback"] == "More emails"
    assert summary["new_pattern_types"] == ["past simple"]  # "word order" only recurred
    assert not {"completed_slots", "deferred_items", "exit_criteria_met"} & set(summary)
    assert "finished_early" in fake_llm.calls[-1].text


async def test_start_without_a_time_budget_is_409(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await make_profile(db, user, minutes_per_session=None)

    response = await client.post("/api/v1/lessons/start")

    assert response.status_code == 409
    assert response.json()["code"] == "TIME_BUDGET_REQUIRED"


async def test_patch_profile_minutes_then_start_succeeds(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user, minutes_per_session=None, time_budget={"sessions_per_week": 5})
    fake_llm.push(curriculum())

    patched = await client.patch("/api/v1/profile", json={"time_budget": {"minutes_per_session": 20}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["time_budget"] == {"sessions_per_week": 5, "minutes_per_session": 20}

    started = await client.post("/api/v1/lessons/start")
    assert started.status_code == 202, started.text
    lesson = await client.get(f"/api/v1/lessons/{started.json()['lesson_id']}")
    assert lesson.json()["payload"]["target_minutes"] == 20


@pytest.mark.parametrize("minutes", [0, 4, 181, "fifteen"])
async def test_patch_profile_rejects_out_of_range_minutes(
    client: httpx.AsyncClient, db: AsyncSession, minutes: object
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    response = await client.patch("/api/v1/profile", json={"time_budget": {"minutes_per_session": minutes}})
    assert response.status_code == 422


async def test_finishing_within_a_minute_of_the_target_is_not_early(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, payload={"curriculum": {}, "target_minutes": 15})
    session = await make_chat_session(db, user, lesson)
    await make_messages(db, session, [0, 4, 8, 12, 14])
    lesson_id = lesson.id
    fake_llm.push(ReportPatch(ops=[]))

    await client.post(f"/api/v1/lessons/{lesson_id}/finish", json={})

    db.expire_all()
    summary = (await db.get(Lesson, lesson_id)).payload["session_summary"]  # type: ignore[union-attr]
    assert (summary["shortfall_minutes"], summary["finished_early"]) == (1, False)
