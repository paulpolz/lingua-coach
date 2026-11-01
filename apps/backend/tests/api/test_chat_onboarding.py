"""Onboarding chat turns end-to-end through the HTTP API."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.models.enums import ChatMessageRole
from app.schemas.llm import OnboardingReply
from tests.factories import make_chat_session, make_user
from tests.fake_llm import RAW_INPUT_TOKENS, FakeLLM, SchemaMismatch
from tests.integration.test_llm_usage_limits import _events
from tests.samples import roadmap


async def _messages(db: AsyncSession) -> list[ChatMessage]:
    db.expire_all()
    return list((await db.execute(select(ChatMessage).order_by(ChatMessage.created_at))).scalars())


async def test_onboarding_reply_keeps_content_and_roadmap_draft(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    draft = roadmap()
    fake_llm.push(OnboardingReply(content="  Here is your plan.  ", course_roadmap=draft))

    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages", json={"content": "I want to travel."})

    assert response.status_code == 200, response.text
    assert fake_llm.calls[-1].schema is OnboardingReply
    body = response.json()
    assert body["content"] == "Here is your plan."
    assert body["metadata"]["course_roadmap_draft"] == draft.model_dump()
    assistants = [m for m in await _messages(db) if m.role == ChatMessageRole.assistant]
    assert len(assistants) == 1
    assert assistants[0].content == "Here is your plan."
    assert assistants[0].metadata_json is not None
    assert assistants[0].metadata_json["course_roadmap_draft"] == draft.model_dump()


async def test_schema_error_completes_usage_as_error_and_skips_assistant_row(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)
    fake_llm.push(SchemaMismatch())

    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages", json={"content": "Hello"})

    assert response.status_code == 502
    assert response.json()["code"] == "LLM_SCHEMA_ERROR"
    events = await _events(db)
    assert events[0].status == "error"
    assert events[0].input_tokens == RAW_INPUT_TOKENS
    assert [m.role for m in await _messages(db)] == [ChatMessageRole.user]
