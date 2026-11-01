"""Lesson chat turns end-to-end through the HTTP API."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mistake import Mistake
from app.schemas.llm import LessonReply, MistakeEntry
from tests.factories import make_chat_session, make_lesson, make_mistake, make_profile, make_user
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


async def test_pattern_labels_are_stored_in_one_canonical_form(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    user_id = user.id  # type: ignore[attr-defined]
    fake_llm.push(
        LessonReply(
            content="Articles!",
            mistakes=[
                MistakeEntry(pattern_type="Articles ", example_text="I saw cat", correction="a cat"),
                MistakeEntry(pattern_type="articles", example_text="I saw dog", correction="a dog"),
            ],
        )
    )

    await client.post(url, json={"content": "I saw cat and dog"})

    db.expire_all()
    rows = list((await db.execute(select(Mistake).where(Mistake.user_id == user_id))).scalars())
    assert [(m.pattern_type, m.occurrence_count) for m in rows] == [("articles", 1)]


async def test_duplicate_pattern_in_one_reply_creates_one_mistake(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    user_id = user.id  # type: ignore[attr-defined]
    await make_mistake(db, user, "articles", occurrence_count=2)  # type: ignore[arg-type]
    fake_llm.push(
        LessonReply(
            content="Watch the tense.",
            mistakes=[
                MistakeEntry(pattern_type="past simple", example_text="I go yesterday", correction="I went"),
                MistakeEntry(pattern_type="past simple", example_text="She eat", correction="She ate"),
                MistakeEntry(pattern_type="articles", example_text="I saw cat", correction="I saw a cat"),
            ],
        ),
        LessonReply(content="Again."),
    )

    assert (await client.post(url, json={"content": "I go yesterday, she eat"})).status_code == 200
    # A second turn must not crash on MultipleResultsFound.
    assert (await client.post(url, json={"content": "ok"})).status_code == 200

    db.expire_all()
    found = list((await db.execute(select(Mistake).where(Mistake.user_id == user_id))).scalars())
    assert sorted(m.pattern_type for m in found) == ["articles", "past simple"]
    rows = {m.pattern_type: m for m in found}
    assert rows["past simple"].occurrence_count == 1
    assert rows["articles"].occurrence_count == 3
    assert rows["articles"].example_text == "I saw cat"
