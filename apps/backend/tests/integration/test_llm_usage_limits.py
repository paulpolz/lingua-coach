"""metered_structured_call and the DB-backed limiter against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import APIError
from app.models.llm_usage import LlmUsageEvent
from app.schemas.llm import LessonCurriculum
from app.services.llm_usage import metered_structured_call, reserve_llm_call
from app.services.structured_llm import ChatTurn
from tests.factories import make_chat_session, make_user
from tests.fake_llm import RAW_INPUT_TOKENS, FakeLLM, SchemaMismatch
from tests.samples import curriculum


async def _events(db: AsyncSession) -> list[LlmUsageEvent]:
    db.expire_all()
    return list((await db.execute(select(LlmUsageEvent))).scalars())


async def test_parse_failure_reports_tokens_and_complete_stores_error_count(
    db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    fake_llm.push(SchemaMismatch())

    with pytest.raises(Exception) as caught:
        await metered_structured_call(
            db,
            user.id,
            "lesson_json",
            model_id="gemini-test",
            schema=LessonCurriculum,
            system_instruction="system",
            history=[ChatTurn(role="user", text="next lesson")],
        )

    assert getattr(caught.value, "code", None) == "LLM_SCHEMA_ERROR"
    events = await _events(db)
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].input_tokens == RAW_INPUT_TOKENS
    assert events[0].input_tokens != 0


async def test_metered_call_traces_a_hashed_user_id(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    fake_llm.push(curriculum())

    await metered_structured_call(
        db,
        user.id,
        "lesson_json",
        model_id="m",
        schema=LessonCurriculum,
        system_instruction="s",
        history=[ChatTurn(role="user", text="x")],
        trace_metadata={"lesson_number": 1},
    )

    metadata = fake_llm.calls[-1].config["metadata"]  # type: ignore[index]
    assert metadata["lesson_number"] == 1
    assert len(metadata["user_id_hash"]) == 16
    assert str(user.id) not in str(metadata)
    events = await _events(db)
    assert [e.status for e in events] == ["ok"]


async def _usage(
    db: AsyncSession, user_id: object, call_type: str, n: int, *, age_seconds: int = 0, tokens: int = 0
) -> None:
    for _ in range(n):
        event = LlmUsageEvent(user_id=user_id, call_type=call_type, input_tokens=tokens, status="ok")
        event.created_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        db.add(event)
    await db.flush()


@pytest.mark.parametrize(
    ("setup", "retry_after"),
    [
        ({"rpm": 3, "minute_calls": 3}, "60"),
        ({"tpm": 100, "minute_calls": 1, "tokens": 90}, "60"),
        ({"rpd": 2, "day_calls": 2}, None),
    ],
)
async def test_global_limits_raise_429_with_retry_after(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, setup: dict, retry_after: str | None
) -> None:
    user = await make_user(db)
    monkeypatch.setattr(settings, "llm_rpm_limit", setup.get("rpm", 1000))
    monkeypatch.setattr(settings, "llm_input_tpm_limit", setup.get("tpm", 10**9))
    monkeypatch.setattr(settings, "llm_rpd_limit", setup.get("rpd", 10**6))
    await _usage(db, user.id, "chat", setup.get("minute_calls", 0), tokens=setup.get("tokens", 0))
    await _usage(db, user.id, "report", setup.get("day_calls", 0), age_seconds=3600)
    await _usage(db, user.id, "lesson_start", 50)  # not an LLM call; never counted

    with pytest.raises(APIError) as caught:
        await reserve_llm_call(db, user.id, "chat", estimated_input_tokens=20)

    assert caught.value.status_code == 429
    assert caught.value.code == "LLM_RATE_LIMIT_EXCEEDED"
    value = caught.value.headers["Retry-After"]
    if retry_after:
        assert value == retry_after
    else:
        assert 82000 < int(value) <= 82800  # oldest call is an hour old in a 24h window


async def test_reserve_under_limits_inserts_a_reserved_row(db: AsyncSession) -> None:
    user = await make_user(db)
    await _usage(db, user.id, "chat", 2, tokens=10)
    event = await reserve_llm_call(db, user.id, "report", estimated_input_tokens=7)
    assert event.status == "reserved" and event.input_tokens == 7


async def test_user_chat_limit_is_429_rate_limit_exceeded(
    client: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    monkeypatch.setattr(settings, "chat_rate_limit_per_hour", 2)
    await _usage(db, user.id, "chat", 2, age_seconds=600)

    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages", json={"content": "hi"})

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert 2900 < int(response.headers["Retry-After"]) <= 3000
