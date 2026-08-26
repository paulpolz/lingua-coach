"""Integration tests for chat sessions + SSE messages against a real
(disposable) Postgres database, with Gemini mocked out.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.profile import Profile
from app.models.user import User
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LEARNER_PROFILE


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def _mark_onboarded(db_session, user_id: str) -> None:
    """Minimal onboarding-complete flag flip — full plan/profile seeding
    lives in tests/test_lesson_chat.py; this file only needs the gate open
    to reach lesson-lookup logic (e.g. 404 for an unknown lesson_id)."""
    user = await db_session.get(User, uuid.UUID(user_id))
    user.onboarding_complete = True
    await db_session.commit()


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event_name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event_name, json.loads(data_line)))
    return events


async def test_create_onboarding_session_is_idempotent(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_onboarding_1")

    resp1 = await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})
    assert resp1.status_code == 201
    body1 = resp1.json()
    assert body1["type"] == "onboarding"
    assert body1["lesson_id"] is None

    resp2 = await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})
    assert resp2.status_code == 201
    assert resp2.json()["id"] == body1["id"]


async def test_create_onboarding_session_concurrent_posts_return_same_id(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_onboarding_race")

    resp1, resp2 = await asyncio.gather(
        client.post("/api/v1/chat/sessions", json={"type": "onboarding"}),
        client.post("/api/v1/chat/sessions", json={"type": "onboarding"}),
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]


async def test_create_lesson_session_returns_404_for_unknown_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_stub")
    await _mark_onboarded(db_session, user_id)
    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_create_lesson_session_without_lesson_id_is_422(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_lesson_missing_id")
    resp = await client.post("/api/v1/chat/sessions", json={"type": "lesson"})
    assert resp.status_code == 422


async def test_messages_ownership_check_returns_404_for_other_users_session(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_owner")
    session_resp = await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})
    session_id = session_resp.json()["id"]

    await _sync_user(client, as_principal, "clerk_intruder")
    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_messages_ownership_check_404_for_unknown_session(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_unknown_session")
    resp = await client.get(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages")
    assert resp.status_code == 404


async def test_post_message_streams_token_and_done_events(
    client: AsyncClient, as_principal, mock_gemini
) -> None:
    await _sync_user(client, as_principal, "clerk_stream_basic")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    mock_gemini(["Hello ", "there, ", "let's get started!"])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi!"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    token_events = [e for e in events if e[0] == "token"]
    done_events = [e for e in events if e[0] == "done"]
    assert [e[1]["text"] for e in token_events] == ["Hello ", "there, ", "let's get started!"]
    assert len(done_events) == 1
    done_data = done_events[0][1]
    assert done_data["content"] == "Hello there, let's get started!"
    assert set(done_data["metadata"].keys()) == {
        "corrections",
        "tips",
        "plan_updates",
        "suggest_finish",
        "course_roadmap_draft",
        "lesson_plan",
        "task_update",
    }
    assert done_data["metadata"]["course_roadmap_draft"] is None
    assert done_data["metadata"]["suggest_finish"] is False

    # GET messages reflects both persisted turns, ordered.
    history_resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    messages = history_resp.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Hi!"
    assert messages[1]["content"] == "Hello there, let's get started!"


async def test_post_message_persists_learner_profile_and_draft_goal(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    clerk_id = "clerk_profile_extraction"
    user_id = await _sync_user(client, as_principal, clerk_id)
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    reply = "I have what I need!\n\n```json:learner_profile\n" + json.dumps(
        VALID_LEARNER_PROFILE
    ) + "\n```"
    mock_gemini([reply])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Here's my situation..."}
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    done_data = next(e[1] for e in events if e[0] == "done")
    assert "json:learner_profile" not in done_data["content"]
    assert done_data["metadata"]["plan_updates"]["goal_summary"] == VALID_LEARNER_PROFILE["goal"]["outcome"]

    result = await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    profile = result.scalar_one()
    assert profile.goal_outcome == VALID_LEARNER_PROFILE["goal"]["outcome"]
    assert profile.target_level == VALID_LEARNER_PROFILE["level"]["self_assessed"]
    assert profile.native_language == VALID_LEARNER_PROFILE["languages"]["native"]
    assert profile.target_language == VALID_LEARNER_PROFILE["languages"]["target"]
    assert profile.interview_completed_at is not None


async def test_post_message_includes_course_roadmap_draft_in_done_metadata(
    client: AsyncClient, as_principal, mock_gemini
) -> None:
    await _sync_user(client, as_principal, "clerk_roadmap_draft")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    reply = "# Your roadmap\nLooks great, right?\n\n```json:course_roadmap\n" + json.dumps(
        VALID_COURSE_ROADMAP
    ) + "\n```"
    mock_gemini([reply])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Show me the plan"}
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    draft = done_data["metadata"]["course_roadmap_draft"]
    assert draft is not None
    assert draft["summary"]["target_plan_days"] == 90
    assert "# Your roadmap" in done_data["content"]


async def test_post_message_emits_error_event_on_gemini_failure(
    client: AsyncClient, as_principal, mock_gemini_error
) -> None:
    await _sync_user(client, as_principal, "clerk_gemini_failure")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]
    mock_gemini_error("simulated timeout")

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi"}
    ) as resp:
        assert resp.status_code == 200
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    assert events[0][0] == "error"
    assert events[0][1]["code"] == "LLM_TIMEOUT"
    assert not any(e[0] == "done" for e in events)


async def test_post_message_emits_error_when_profile_persist_fails(
    client: AsyncClient, as_principal, mock_gemini, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from app.api.v1 import chat as chat_mod

    async def _boom(*_a, **_k):
        raise SQLAlchemyError("simulated persist failure")

    monkeypatch.setattr(chat_mod, "_persist_learner_profile", _boom)

    user_id = await _sync_user(client, as_principal, "clerk_profile_persist_fail")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]
    reply = "I have what I need!\n\n```json:learner_profile\n" + json.dumps(
        VALID_LEARNER_PROFILE
    ) + "\n```"
    mock_gemini([reply])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Here's my situation..."},
    ) as resp:
        assert resp.status_code == 200
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    assert error_events[0][1]["code"] == "PROFILE_PERSIST_FAILED"
    assert "profile" in error_events[0][1]["message"].lower()
    assert not any(e[0] == "done" for e in events)

    result = await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    assert result.scalar_one_or_none() is None

    history_resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    roles = [m["role"] for m in history_resp.json()["messages"]]
    assert roles == ["user"]


async def test_post_message_rejects_empty_and_oversized_content(
    client: AsyncClient, as_principal, mock_gemini
) -> None:
    await _sync_user(client, as_principal, "clerk_validation")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]
    mock_gemini(["reply"])

    empty_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "   "}
    )
    assert empty_resp.status_code == 422

    from app.config import settings

    too_long = "a" * (settings.max_message_chars + 1)
    long_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": too_long}
    )
    assert long_resp.status_code == 422


async def test_post_message_enforces_rate_limit(
    client: AsyncClient, as_principal, mock_gemini, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.services import rate_limit

    monkeypatch.setattr(settings, "chat_rate_limit_per_hour", 1)
    rate_limit.reset()

    await _sync_user(client, as_principal, "clerk_rate_limited")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]
    mock_gemini(["ok"])

    first = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "one"}
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "two"}
    )
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMIT_EXCEEDED"
    rate_limit.reset()
