"""Lesson chat turns end-to-end through the HTTP API."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.llm import LessonReply
from tests.factories import make_chat_session, make_lesson, make_profile, make_user
from tests.fake_llm import FakeLLM

METADATA_KEYS = {
    "corrections",
    "tips",
    "plan_updates",
    "suggest_finish",
    "course_roadmap_draft",
    "lesson_plan",
    "task_update",
}


async def _lesson_chat(db: AsyncSession) -> tuple[str, object]:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, payload={"curriculum": {"grammar_focus": "past simple"}})
    session = await make_chat_session(db, user, lesson)
    return f"/api/v1/chat/sessions/{session.id}/messages", user


async def test_lesson_reply_completed_task_ids_become_task_update(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, _ = await _lesson_chat(db)
    fake_llm.push(LessonReply(content="Nice work on the order.", completed_task_ids=["warmup", "exit"]))

    response = await client.post(url, json={"content": "I would like a coffee."})

    assert response.status_code == 200, response.text
    assert fake_llm.calls[-1].schema is LessonReply
    body = response.json()
    assert body["content"] == "Nice work on the order."
    assert set(body["metadata"]) == METADATA_KEYS
    assert body["metadata"]["task_update"] == {"completed_task_ids": ["warmup", "exit"]}
