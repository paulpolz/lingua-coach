"""Error envelope and the LLM failure → HTTP mapping."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus
from app.models.job import Job
from app.schemas.llm import LessonReply
from app.services.agents.runner import LLMError
from tests.chat_turn import post_turn
from tests.conftest import Auth
from tests.factories import make_chat_session, make_lesson, make_profile, make_user, roadmap_dict
from tests.fake_llm import FakeLLM, SchemaMismatch
from tests.integration.test_llm_usage_limits import _events

RAW_SECRET = "upstream said: key=AIza-secret-123 project=internal"


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError(RAW_SECRET), "LLM_TIMEOUT"),
        (RuntimeError(f"RESOURCE_EXHAUSTED {RAW_SECRET}"), "LLM_QUOTA_EXCEEDED"),
        (RuntimeError(RAW_SECRET), "LLM_API_ERROR"),
        (LLMError(RAW_SECRET, code="LLM_CONFIG_ERROR"), "LLM_CONFIG_ERROR"),
        (SchemaMismatch(), "LLM_SCHEMA_ERROR"),
    ],
)
async def test_llm_failures_are_sse_errors_without_leaking_raw_text(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, failure: object, code: str
) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    fake_llm.push(failure)  # type: ignore[arg-type]

    response = await post_turn(client, f"/api/v1/chat/sessions/{session.id}/messages", "Hi")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == code
    assert "secret" not in response.text
    assert "upstream" not in body["detail"]
    assert "X-Request-ID" in response.headers


MALFORMED = [
    ("get", "/api/v1/lessons/not-a-uuid"),
    ("post", "/api/v1/lessons/not-a-uuid/stop"),
    ("post", "/api/v1/lessons/not-a-uuid/finish"),
    ("get", "/api/v1/chat/sessions/not-a-uuid/messages"),
    ("post", "/api/v1/chat/sessions/not-a-uuid/messages/stream"),
    ("get", "/api/v1/jobs/not-a-uuid"),
]


@pytest.mark.parametrize(("method", "path"), MALFORMED)
async def test_malformed_ids_are_422(client: httpx.AsyncClient, db: AsyncSession, method: str, path: str) -> None:
    await make_user(db)
    response = await client.request(method, path, json={"content": "hi"} if method == "post" else None)
    assert response.status_code == 422
    assert "code" not in response.json()  # FastAPI's validation body; clients treat it as "not found"


async def test_malformed_ids_in_bodies_are_422(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    chat = await client.post("/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": "nope"})
    # A valid roadmap, so only the malformed id can cause the 422.
    accept = await client.post(
        "/api/v1/onboarding/accept", json={"session_id": "nope", "course_roadmap": roadmap_dict()}
    )
    for response in (chat, accept):
        assert response.status_code == 422
        assert "code" not in response.json()
        assert response.json()["detail"][0]["loc"][-1] in ("lesson_id", "session_id")


async def test_someone_elses_resources_are_404(client: httpx.AsyncClient, db: AsyncSession, auth: Auth) -> None:
    owner = await make_user(db, clerk_user_id="owner")
    await make_user(db, clerk_user_id="intruder")
    lesson = await make_lesson(db, owner)
    session = await make_chat_session(db, owner, lesson)
    job = Job(user_id=owner.id, type="lesson_generate", status=JobStatus.pending)
    db.add(job)
    await db.flush()
    auth.as_clerk_id("intruder")

    for method, path in [
        ("get", f"/api/v1/lessons/{lesson.id}"),
        ("post", f"/api/v1/lessons/{lesson.id}/stop"),
        ("get", f"/api/v1/chat/sessions/{session.id}/messages"),
        ("get", f"/api/v1/jobs/{job.id}"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 404, path
        assert response.json()["code"] == "NOT_FOUND"
    missing = await client.get(f"/api/v1/lessons/{uuid.uuid4()}")
    assert missing.status_code == 404


async def test_persist_failure_is_an_sse_error(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, payload={"curriculum": {}, "target_minutes": 15})
    session = await make_chat_session(db, user, lesson)
    fake_llm.push(LessonReply(content="ok"))

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("disk full")

    monkeypatch.setattr("app.services.chat_turns._upsert_mistakes", broken)
    response = await post_turn(client, f"/api/v1/chat/sessions/{session.id}/messages", "hi")

    assert response.status_code == 200
    assert response.json()["code"] == "PERSIST_FAILED"
    events = await _events(db)
    assert len(events) == 1 and events[0].status == "ok"


async def test_unhandled_errors_use_the_envelope(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("secret internals")

    monkeypatch.setattr("app.api.v1.auth.User", boom)
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        response = await c.post("/api/v1/auth/sync")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "code": "INTERNAL_ERROR"}
