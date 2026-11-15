"""SSE chat turns. The JSON route stays available when streaming is off."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models.chat import ChatMessage
from app.models.enums import ChatMessageRole
from app.models.llm_usage import LlmUsageEvent
from app.schemas.llm import LessonReply, OnboardingReply
from app.services.agents.tools import language_policy_tool
from tests.factories import make_chat_session, make_lesson, make_profile, make_user
from tests.fake_llm import RAW_INPUT_TOKENS, FakeLLM, LLMCall, ToolRound
from tests.integration.test_llm_usage_limits import _events as usage_rows
from tests.integration.test_llm_usage_limits import _usage


def parse_sse(body: str) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data += line.removeprefix("data:").strip()
        parsed.append((name, json.loads(data)))
    return parsed


async def _onboarding(db: AsyncSession) -> str:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    return f"/api/v1/chat/sessions/{session.id}/messages"


async def test_stream_route_is_404_while_json_returns_the_turn(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url = await _onboarding(db)
    fake_llm.push(OnboardingReply(content="Hello there."))

    json_response = await client.post(url, json={"content": "Hi"})
    stream_response = await client.post(f"{url}/stream", json={"content": "Hi again"})

    assert json_response.status_code == 200, json_response.text
    assert json_response.json()["content"] == "Hello there."
    assert stream_response.status_code == 404
    assert stream_response.json()["code"] == "STREAMING_DISABLED"


async def test_json_turn_still_returns_when_streaming_is_on(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    url = await _onboarding(db)
    fake_llm.push(OnboardingReply(content="Still JSON."))

    response = await client.post(url, json={"content": "Hi"})

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Still JSON."


async def test_reply_fallback_emits_one_token_then_structured_then_done(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    url = await _onboarding(db)
    fake_llm.push(OnboardingReply(content="Here is the next question."))

    response = await client.post(f"{url}/stream", json={"content": "I want to travel."})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [name for name, _payload in events] == ["token", "structured", "done"]
    assert events[0][1] == {"delta": "Here is the next question."}
    assert events[1][1]["content"] == "Here is the next question."
    assert "message_id" in events[2][1]
    rows = await usage_rows(db)
    assert len(rows) == 1 and rows[0].status == "ok" and rows[0].input_tokens == RAW_INPUT_TOKENS


async def test_fallback_stays_off_when_the_setting_is_off(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    monkeypatch.setattr(settings, "chat_stream_reply_fallback", False)
    url = await _onboarding(db)
    fake_llm.push(OnboardingReply(content="No token."))

    response = await client.post(f"{url}/stream", json={"content": "Hi"})

    assert [name for name, _payload in parse_sse(response.text)] == ["structured", "done"]


async def test_stream_order_is_token_tool_start_tool_end_structured_done(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    url = await _onboarding(db)
    fake_llm.push(
        ToolRound(
            reply=OnboardingReply(content="Now the target language."),
            tool_name=language_policy_tool.name,
            text="One moment.",
        )
    )

    response = await client.post(f"{url}/stream", json={"content": "Russian."})

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    names = [name for name, _payload in events]
    assert names == ["token", "tool_start", "tool_end", "structured", "done"]
    assert events[0][1] == {"delta": "One moment."}
    assert events[1][1] == {"name": language_policy_tool.name}
    assert events[2][1] == {"name": language_policy_tool.name}
    assert events[3][1]["content"] == "Now the target language."
    rows = await usage_rows(db)
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].input_tokens == RAW_INPUT_TOKENS * 2


async def test_stream_rate_limit_returns_429_without_opening_sse(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    monkeypatch.setattr(settings, "llm_rpm_limit", 1)
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    await _usage(db, user.id, "chat", 1)
    fake_llm.push(OnboardingReply(content="should not run"))

    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages/stream", json={"content": "Hi"})

    assert response.status_code == 429, response.text
    assert response.json()["code"] == "LLM_RATE_LIMIT_EXCEEDED"
    assert response.headers["Retry-After"] == "60"
    assert not response.headers["content-type"].startswith("text/event-stream")
    assert fake_llm.calls == []
    rows = await usage_rows(db)
    assert len(rows) == 1 and rows[0].status == "ok"
    db.expire_all()
    assert list((await db.execute(select(ChatMessage))).scalars()) == []


async def test_stream_error_replaces_done(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    url = await _onboarding(db)
    fake_llm.push(TimeoutError("upstream secret"))

    response = await client.post(f"{url}/stream", json={"content": "Hi"})

    events = parse_sse(response.text)
    assert [name for name, _payload in events] == ["error"]
    assert events[0][1]["code"] == "LLM_TIMEOUT"
    assert "secret" not in response.text
    assert (await usage_rows(db))[0].status == "error"
    db.expire_all()
    roles = list((await db.execute(select(ChatMessage.role))).scalars())
    assert roles == [ChatMessageRole.user]


async def test_stream_persist_failure_does_not_mark_the_model_call_as_error(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_streaming_enabled", True)
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, payload={"curriculum": {}, "target_minutes": 15})
    session = await make_chat_session(db, user, lesson)
    fake_llm.push(LessonReply(content="ok"))

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("disk full")

    monkeypatch.setattr("app.api.v1.chat._upsert_mistakes", broken)
    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages/stream", json={"content": "hi"})

    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "PERSIST_FAILED"
    assert "done" not in [name for name, _payload in events]
    assert "disk" not in response.text
    assert (await usage_rows(db))[0].status == "ok"


async def test_missing_checkpointer_is_503_and_writes_nothing(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url = await _onboarding(db)
    app.state.checkpointer = None
    fake_llm.push(OnboardingReply(content="should not run"))

    response = await client.post(url, json={"content": "Hi"})

    assert response.status_code == 503
    assert response.json()["code"] == "CHECKPOINTER_UNAVAILABLE"
    assert fake_llm.calls == []
    db.expire_all()
    assert list((await db.execute(select(ChatMessage))).scalars()) == []
    assert list((await db.execute(select(LlmUsageEvent))).scalars()) == []


async def test_user_row_is_committed_before_the_model_and_thread_is_the_session(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    session_id = session.id
    seen: dict[str, list[str]] = {}

    async def during_call(_call: LLMCall) -> OnboardingReply:
        db.expire_all()
        rows = list((await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))).scalars())
        seen["roles"] = [row.role.value for row in rows]
        return OnboardingReply(content="Noted.")

    fake_llm.push(during_call)
    response = await client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "I travel."})

    assert response.status_code == 200, response.text
    assert seen["roles"] == ["user"]
    assert fake_llm.calls[-1].config is not None
    assert fake_llm.calls[-1].config["configurable"]["thread_id"] == str(session_id)
    listed = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    assert listed.status_code == 200
    assert [(item["role"], item["content"]) for item in listed.json()["messages"]] == [
        ("user", "I travel."),
        ("assistant", "Noted."),
    ]


async def test_second_turn_keeps_the_thread_and_does_not_sum_old_tokens(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    first = await make_chat_session(db, user)
    lesson = await make_lesson(db, user, payload={"curriculum": {}, "target_minutes": 15})
    other_session = await make_chat_session(db, user, lesson)
    first_id, other_id = first.id, other_session.id
    fake_llm.push(OnboardingReply(content="First."), OnboardingReply(content="Second."))

    await client.post(f"/api/v1/chat/sessions/{first_id}/messages", json={"content": "alpha-only-phrase"})
    await client.post(f"/api/v1/chat/sessions/{first_id}/messages", json={"content": "beta-follow-up"})

    assert "alpha-only-phrase" in fake_llm.calls[-1].text
    rows = await usage_rows(db)
    assert len(rows) == 2
    assert [row.input_tokens for row in rows] == [RAW_INPUT_TOKENS, RAW_INPUT_TOKENS]
    assert [row.status for row in rows] == ["ok", "ok"]

    fake_llm.push(LessonReply(content="Other."))
    other = await client.post(f"/api/v1/chat/sessions/{other_id}/messages", json={"content": "unrelated"})
    assert other.status_code == 200, other.text
    assert "alpha-only-phrase" not in fake_llm.calls[-1].text
    assert fake_llm.calls[-1].config is not None
    assert fake_llm.calls[-1].config["configurable"]["thread_id"] == str(other_id)
