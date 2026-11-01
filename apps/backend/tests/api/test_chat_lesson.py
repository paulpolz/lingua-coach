"""Lesson chat turns end-to-end through the HTTP API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.chat import ChatMessage
from app.models.enums import LessonStatus
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.schemas.llm import LessonReply, MistakeEntry, PracticeResult
from tests.factories import make_chat_session, make_lesson, make_messages, make_mistake, make_profile, make_user
from tests.fake_llm import FakeLLM, LLMCall

METADATA_KEYS = {"corrections", "tips", "plan_updates", "suggest_finish", "course_roadmap_draft", "practiced", "timing"}


async def _lesson_chat(db: AsyncSession, *, minutes: list[float] | None = None, target: int = 15) -> tuple[str, object]:
    user = await make_user(db)
    await make_profile(db, user, minutes_per_session=target)
    lesson = await make_lesson(
        db, user, payload={"curriculum": {"grammar_focus": "past simple"}, "target_minutes": target}
    )
    session = await make_chat_session(db, user, lesson)
    if minutes:
        await make_messages(db, session, minutes)
    return f"/api/v1/chat/sessions/{session.id}/messages", user


async def test_lesson_turn_returns_typed_metadata_with_timing(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, _ = await _lesson_chat(db, minutes=[0, 2, 6])
    fake_llm.push(LessonReply(content="Nice work on the order."))

    response = await client.post(url, json={"content": "I would like a coffee."})

    assert response.status_code == 200, response.text
    assert fake_llm.calls[-1].schema is LessonReply
    body = response.json()
    assert body["content"] == "Nice work on the order."
    assert set(body["metadata"]) == METADATA_KEYS
    assert body["metadata"]["timing"] == {"active_minutes": 6, "target_minutes": 15}
    assert "Time: 6 of 15 min used." in fake_llm.calls[-1].text


async def test_suggest_finish_is_held_back_until_the_time_budget_is_used(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, _ = await _lesson_chat(db, minutes=[0, 2.5, 5])
    fake_llm.push(LessonReply(content="All done, great job!", suggest_finish=True))

    response = await client.post(url, json={"content": "done?"})

    assert response.json()["metadata"]["suggest_finish"] is False
    db.expire_all()
    stored = (await db.execute(select(ChatMessage).where(ChatMessage.content == "All done, great job!"))).scalar_one()
    assert stored.metadata_json is not None and stored.metadata_json["suggest_finish"] is False


async def test_suggest_finish_passes_in_the_last_minute(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, _ = await _lesson_chat(db, minutes=[0, 4, 8, 12, 14])
    fake_llm.push(LessonReply(content="Recap: ...", suggest_finish=True))

    response = await client.post(url, json={"content": "ok"})

    assert response.json()["metadata"]["suggest_finish"] is True


async def test_solid_practice_pushes_review_out_and_closes_only_in_a_second_lesson(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    user_id = user.id  # type: ignore[attr-defined]
    due_at = datetime.now(UTC) - timedelta(hours=1)
    mistake = await make_mistake(db, user, "past simple", occurrence_count=1, next_review_at=due_at)  # type: ignore[arg-type]
    mistake_id = mistake.id
    solid = PracticeResult(aspect="review", item="Past simple", result="solid")
    fake_llm.push(*(LessonReply(content="Correct, no hints!", practiced=[solid]) for _ in range(3)))

    # Two solid turns in the same lesson count once.
    await client.post(url, json={"content": "I went home."})
    await client.post(url, json={"content": "She went too."})
    db.expire_all()
    first = await db.get(Mistake, mistake_id)
    assert first is not None and first.solid_streak == 1 and first.resolved_at is None
    assert first.next_review_at is not None and first.next_review_at > datetime.now(UTC) + timedelta(days=2)

    # A solid result in a later lesson closes the pattern.
    old = (await db.execute(select(Lesson).where(Lesson.user_id == user_id))).scalar_one()
    old.status = LessonStatus.accomplished
    await db.flush()
    await db.refresh(user)  # type: ignore[arg-type]
    lesson2 = await make_lesson(db, user, lesson_number=2, payload={"curriculum": {}, "target_minutes": 15})  # type: ignore[arg-type]
    session2 = await make_chat_session(db, user, lesson2)  # type: ignore[arg-type]
    await client.post(f"/api/v1/chat/sessions/{session2.id}/messages", json={"content": "We went."})
    db.expire_all()
    closed = await db.get(Mistake, mistake_id)
    assert closed is not None and closed.resolved_at is not None and closed.next_review_at is None


async def test_reported_metadata_timing_is_measured_after_the_reply(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM, db_conn: AsyncConnection
) -> None:
    url, _ = await _lesson_chat(db, minutes=[0, 4, 8, 12])

    async def two_minutes_pass(_call: LLMCall) -> LessonReply:
        # Shift every message two minutes into the past: the reply arrives two minutes later.
        async with AsyncSession(bind=db_conn, join_transaction_mode="create_savepoint") as other:
            await other.execute(update(ChatMessage).values(created_at=ChatMessage.created_at - timedelta(minutes=2)))
            await other.commit()
        return LessonReply(content="Recap: good work.", suggest_finish=True)

    fake_llm.push(two_minutes_pass)

    response = await client.post(url, json={"content": "done"})

    assert "Time: 12 of 15 min used." in fake_llm.calls[-1].text
    metadata = response.json()["metadata"]
    assert metadata["timing"] == {"active_minutes": 14, "target_minutes": 15}
    assert metadata["suggest_finish"] is True  # the guard uses the fresh value (14 >= 15 - 1)


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


async def test_a_new_mistake_reopens_a_closed_pattern(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    closed = await make_mistake(
        db, user, "articles", resolved_at=datetime.now(UTC), next_review_at=None, solid_streak=2
    )  # type: ignore[arg-type]
    closed_id = closed.id
    fake_llm.push(
        LessonReply(
            content="Watch the article.",
            mistakes=[MistakeEntry(pattern_type="articles", example_text="I saw cat", correction="a cat")],
        )
    )

    await client.post(url, json={"content": "I saw cat"})

    db.expire_all()
    reopened = await db.get(Mistake, closed_id)
    assert reopened is not None and reopened.resolved_at is None and reopened.solid_streak == 0
    assert reopened.occurrence_count == 2


async def test_shaky_result_resets_the_streak_and_solid_grammar_updates_mastery(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    user_id = user.id  # type: ignore[attr-defined]
    mistake = await make_mistake(db, user, "word order", solid_streak=1)  # type: ignore[arg-type]
    mistake_id = mistake.id
    fake_llm.push(
        LessonReply(
            content="Close!",
            practiced=[
                PracticeResult(aspect="review", item="word order", result="shaky"),
                PracticeResult(aspect="grammar", item="past simple", result="solid"),
            ],
        )
    )

    response = await client.post(url, json={"content": "Yesterday went I home."})

    assert [p["result"] for p in response.json()["metadata"]["practiced"]] == ["shaky", "solid"]
    db.expire_all()
    assert (await db.get(Mistake, mistake_id)).solid_streak == 0  # type: ignore[union-attr]
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()
    assert profile.grammar_mastery == {"past simple": "solid"}


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


async def test_legacy_lesson_without_target_falls_back_to_the_profile(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user, minutes_per_session=20)
    legacy = {"version": 1, "curriculum": {"slots": [{"id": "warmup", "label": "W", "exercise_set": "x"}]}}
    lesson = await make_lesson(db, user, payload=legacy)
    session = await make_chat_session(db, user, lesson)
    fake_llm.push(LessonReply(content="Hi"))

    response = await client.post(f"/api/v1/chat/sessions/{session.id}/messages", json={"content": "hi"})

    assert response.status_code == 200
    assert response.json()["metadata"]["timing"] == {"active_minutes": 0, "target_minutes": 20}


async def test_one_reply_moves_a_pattern_at_most_one_step(
    client: httpx.AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    url, user = await _lesson_chat(db)
    mistake = await make_mistake(db, user, "past simple")  # type: ignore[arg-type]
    mistake_id = mistake.id
    fake_llm.push(
        LessonReply(
            content="Correct!",
            practiced=[
                PracticeResult(aspect="review", item="past simple", result="solid"),
                PracticeResult(aspect="grammar", item="past simple", result="solid"),
            ],
        )
    )

    await client.post(url, json={"content": "I went."})

    db.expire_all()
    still_open = await db.get(Mistake, mistake_id)
    assert still_open is not None and still_open.solid_streak == 1 and still_open.resolved_at is None
