"""Phase 4 backend: lesson chat sessions + SSE messages against a real
(disposable) Postgres database, with Gemini mocked out.

Covers docs/implementation-readiness.md §6-8 (`POST /chat/sessions`
type=lesson, lesson-mode SSE `done` metadata), docs/tech_requirements/
database.md's `mistakes` upsert rule + spaced-repetition schedule, and
backend.md's "Plan adaptation (chat-only)" recompute-on-`target_plan_days`
rule.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import LearningGoalStatus, LearningPlanStatus, LessonStatus
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LESSON_CURRICULUM


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def _seed_onboarded_user(db_session, user_id: str) -> None:
    user = await db_session.get(User, uuid.UUID(user_id))
    user.onboarding_complete = True
    goal = LearningGoal(
        user_id=uuid.UUID(user_id),
        goal_statement="Speak confidently in daily work meetings",
        status=LearningGoalStatus.active,
    )
    db_session.add(goal)
    await db_session.flush()
    plan = LearningPlan(
        user_id=uuid.UUID(user_id),
        learning_goal_id=goal.id,
        status=LearningPlanStatus.accepted,
        roadmap=VALID_COURSE_ROADMAP,
        current_milestone_index=0,
        accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(plan)
    await db_session.commit()


async def _create_active_lesson(
    db_session, user_id: str, *, lesson_number: int = 1, curriculum: dict | None = None
) -> Lesson:
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=lesson_number,
        payload={
            "version": 1,
            "curriculum": curriculum if curriculum is not None else VALID_LESSON_CURRICULUM,
            "session_summary": None,
        },
        status=LessonStatus.active,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)
    return lesson


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


def _lesson_turn_reply(text: str, **overrides: object) -> str:
    payload = {
        "corrections": [],
        "tips": [],
        "plan_updates": None,
        "suggest_finish": False,
        "mistakes": [],
    }
    payload.update(overrides)
    return f"{text}\n\n```json:lesson_turn\n{json.dumps(payload)}\n```"


# --- POST /chat/sessions type=lesson -----------------------------------


async def test_create_lesson_session_returns_404_for_unknown_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_chat_unknown")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_create_lesson_session_returns_404_for_other_users_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_lesson_chat_owner")
    await _seed_onboarded_user(db_session, owner_id)
    lesson = await _create_active_lesson(db_session, owner_id)

    intruder_id = await _sync_user(client, as_principal, "clerk_lesson_chat_intruder")
    await _seed_onboarded_user(db_session, intruder_id)
    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_create_lesson_session_rejects_accomplished_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_chat_accomplished")
    await _seed_onboarded_user(db_session, user_id)
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=1,
        payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": {}},
        status=LessonStatus.accomplished,
        started_at=datetime.now(timezone.utc),
        accomplished_at=datetime.now(timezone.utc),
    )
    db_session.add(lesson)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "LESSON_NOT_ACTIVE"


async def test_create_lesson_session_allows_generating_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_chat_generating")
    await _seed_onboarded_user(db_session, user_id)
    lesson = Lesson(
        user_id=uuid.UUID(user_id), lesson_number=1, payload={}, status=LessonStatus.generating
    )
    db_session.add(lesson)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == "lesson"


async def test_create_lesson_session_is_idempotent(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_chat_idempotent")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    resp1 = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    resp2 = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]
    assert resp1.json()["lesson_id"] == str(lesson.id)


async def test_create_lesson_session_requires_onboarding_complete(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_lesson_chat_gate")
    resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


# --- POST /chat/sessions/{id}/messages for lesson sessions --------------


async def test_lesson_message_streams_and_persists_done_metadata(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_msg_basic")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    corrections = [{"span": "I goed", "correction": "I went", "type": "grammar", "note": "irregular past"}]
    tips = ["Use 'finished' with a specific time."]
    reply = _lesson_turn_reply("Nice try! Let's keep going.", corrections=corrections, tips=tips)
    mock_gemini([reply])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Yesterday I goed to the store."},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    token_events = [e for e in events if e[0] == "token"]
    done_events = [e for e in events if e[0] == "done"]
    assert len(token_events) == 1
    assert len(done_events) == 1

    done_data = done_events[0][1]
    assert "json:lesson_turn" not in done_data["content"]
    assert "Nice try!" in done_data["content"]
    assert done_data["metadata"]["corrections"] == corrections
    assert done_data["metadata"]["tips"] == tips
    assert done_data["metadata"]["plan_updates"] is None
    assert done_data["metadata"]["suggest_finish"] is False
    assert done_data["metadata"]["course_roadmap_draft"] is None
    assert set(done_data["metadata"].keys()) == {
        "corrections",
        "tips",
        "plan_updates",
        "suggest_finish",
        "course_roadmap_draft",
        "lesson_plan",
        "task_update",
    }

    history_resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    messages = history_resp.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "json:lesson_turn" not in messages[1]["content"]


async def test_lesson_message_suggest_finish_passes_through(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_msg_finish")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    mock_gemini([_lesson_turn_reply("Great work — you've hit every exit criterion!", suggest_finish=True)])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Done with everything!"}
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    assert done_data["metadata"]["suggest_finish"] is True


async def test_lesson_message_missing_lesson_turn_block_defaults_gracefully(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    """If the model forgets the `lesson_turn` block, the turn must not fail —
    all fields default to empty/false/null (extraction.py contract)."""
    user_id = await _sync_user(client, as_principal, "clerk_lesson_msg_no_block")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    mock_gemini(["Just a plain reply with no structured block."])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi"}
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    assert done_data["metadata"] == {
        "corrections": [],
        "tips": [],
        "plan_updates": None,
        "suggest_finish": False,
        "course_roadmap_draft": None,
        "lesson_plan": None,
        "task_update": None,
    }


async def test_lesson_message_emits_error_event_on_gemini_failure(
    client: AsyncClient, as_principal, mock_gemini_error, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_msg_gemini_failure")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

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


async def test_lesson_message_ownership_check_returns_404_for_other_users_session(
    client: AsyncClient, as_principal, db_session
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_lesson_msg_owner")
    await _seed_onboarded_user(db_session, owner_id)
    lesson = await _create_active_lesson(db_session, owner_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    intruder_id = await _sync_user(client, as_principal, "clerk_lesson_msg_intruder")
    await _seed_onboarded_user(db_session, intruder_id)
    resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi"}
    )
    assert resp.status_code == 404


# --- Mistakes upsert (database.md upsert rule + spaced repetition) ------


async def test_lesson_message_mistakes_upsert_creates_new_row(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_mistakes_new")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    mistakes = [
        {
            "pattern_type": "missing articles",
            "example_text": "I went to store yesterday",
            "correction": "I went to the store yesterday",
        }
    ]
    mock_gemini([_lesson_turn_reply("Let's fix that.", mistakes=mistakes)])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I went to store yesterday"},
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    result = await db_session.execute(select(Mistake).where(Mistake.user_id == uuid.UUID(user_id)))
    mistake = result.scalar_one()
    assert mistake.pattern_type == "missing articles"
    assert mistake.example_text == "I went to store yesterday"
    assert mistake.correction == "I went to the store yesterday"
    assert mistake.occurrence_count == 1
    assert mistake.lesson_id == lesson.id
    assert mistake.next_review_at is not None
    delta_seconds = (mistake.next_review_at - mistake.last_seen_at).total_seconds()
    assert abs(delta_seconds - timedelta(days=1).total_seconds()) < 5


async def test_lesson_message_mistakes_upsert_increments_on_repeat(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_mistakes_repeat")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    mistake_item = {"pattern_type": "missing articles", "example_text": "I went to store"}
    mock_gemini([_lesson_turn_reply("Again!", mistakes=[mistake_item])])
    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "I went to store"}
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    result = await db_session.execute(select(Mistake).where(Mistake.user_id == uuid.UUID(user_id)))
    mistake = result.scalar_one()
    assert mistake.occurrence_count == 1
    first_review_delta = (mistake.next_review_at - mistake.last_seen_at).total_seconds()
    assert abs(first_review_delta - timedelta(days=1).total_seconds()) < 5
    mistake_id = mistake.id

    repeat_item = {
        "pattern_type": "missing articles",
        "example_text": "I saw store on the corner",
        "correction": "I saw a store on the corner",
    }
    mock_gemini([_lesson_turn_reply("Same pattern again.", mistakes=[repeat_item])])
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I saw store on the corner"},
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    # Written by a different (request-scoped) session — `refresh()` the
    # already-identity-mapped object rather than re-`select()`ing it, since
    # a plain re-`select()` on this same `db_session` would otherwise return
    # the stale cached object instead of re-reading the committed row.
    await db_session.refresh(mistake)
    all_rows = (
        (await db_session.execute(select(Mistake).where(Mistake.user_id == uuid.UUID(user_id))))
        .scalars()
        .all()
    )
    assert len(all_rows) == 1  # upsert, not a new row
    assert mistake.id == mistake_id
    assert mistake.occurrence_count == 2
    assert mistake.example_text == "I saw store on the corner"
    assert mistake.correction == "I saw a store on the corner"
    second_review_delta = (mistake.next_review_at - mistake.last_seen_at).total_seconds()
    assert abs(second_review_delta - timedelta(days=3).total_seconds()) < 5


# --- plan_updates application + projected_completion_at recompute ------


async def test_lesson_message_plan_updates_recomputes_projected_completion(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_plan_updates")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    profile = Profile(
        user_id=uuid.UUID(user_id),
        target_plan_days=90,
        pace_window_hours=24,
    )
    db_session.add(profile)
    await db_session.commit()

    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    plan_updates = {"target_plan_days": 60}
    mock_gemini([_lesson_turn_reply("Sounds good, let's shorten the plan.", plan_updates=plan_updates)])

    before = datetime.now(timezone.utc)
    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Can we shorten my plan to 60 days?"},
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    assert done_data["metadata"]["plan_updates"]["target_plan_days"] == 60

    await db_session.refresh(profile)
    assert profile.target_plan_days == 60
    assert profile.projected_completion_at is not None
    # No accomplished lessons yet -> remaining = 60 plan days at 24h each.
    expected = before + timedelta(hours=60 * 24)
    assert abs((profile.projected_completion_at - expected).total_seconds()) < 30

    events_result = await db_session.execute(
        select(ProgressEvent).where(ProgressEvent.user_id == uuid.UUID(user_id))
    )
    progress_events = events_result.scalars().all()
    assert any(e.event_type == "plan_updated" for e in progress_events)
    plan_updated_event = next(e for e in progress_events if e.event_type == "plan_updated")
    assert plan_updated_event.payload == {"target_plan_days": 60}


async def test_lesson_message_plan_updates_partial_fields_only(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    """Only fields present in `plan_updates` are patched; unrelated profile
    fields are left untouched (skills/backend.md: "omit fields that are not
    changing")."""
    user_id = await _sync_user(client, as_principal, "clerk_plan_updates_partial")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    profile = Profile(
        user_id=uuid.UUID(user_id),
        target_plan_days=90,
        pace_window_hours=24,
        target_level="B1",
    )
    db_session.add(profile)
    await db_session.commit()

    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    plan_updates = {"topics": ["negotiation", "small talk"]}
    mock_gemini([_lesson_turn_reply("Got it, focusing more on negotiation.", plan_updates=plan_updates)])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I want to focus more on negotiation and small talk"},
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    await db_session.refresh(profile)
    assert profile.target_plan_days == 90  # unchanged
    assert profile.target_level == "B1"  # unchanged
    assert (profile.focus or {}).get("topic_priorities") == ["negotiation", "small talk"]


async def test_lesson_message_exposes_lesson_plan_and_task_update_in_metadata(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_msg_checklist")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    plan = {"tasks": [{"id": "warmup", "label": "Warm-up retrieval", "minutes": 5}]}
    update = {"completed_task_ids": ["warmup"]}
    reply = (
        "Here's today's plan: warm-up for about 5 minutes.\n\n"
        f"```json:lesson_plan\n{json.dumps(plan)}\n```\n"
        + _lesson_turn_reply("Let's start.")
        + f"\n```json:task_update\n{json.dumps(update)}\n```"
    )
    mock_gemini([reply])

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi"}
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    assert "Here's today's plan" in done_data["content"]
    assert "json:lesson_plan" not in done_data["content"]
    assert done_data["metadata"]["lesson_plan"] == plan
    assert done_data["metadata"]["task_update"] == update


async def test_lesson_message_includes_vocab_formats_for_review_slot(
    client: AsyncClient, as_principal, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    async def _fake_stream_chat(*, system_instruction: str, history: list, **_kw):
        captured["system_instruction"] = system_instruction
        yield _lesson_turn_reply("Let's review this week's words.")

    monkeypatch.setattr("app.api.v1.chat.stream_chat", _fake_stream_chat)

    user_id = await _sync_user(client, as_principal, "clerk_lesson_vocab_review")
    await _seed_onboarded_user(db_session, user_id)
    curriculum = copy.deepcopy(VALID_LESSON_CURRICULUM)
    curriculum["slots"].append(
        {
            "id": "vocab_review",
            "label": "Week-end vocabulary review",
            "exercise_set": "Format A drills on this week's words",
        }
    )
    lesson = await _create_active_lesson(db_session, user_id, curriculum=curriculum)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Ready"}
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    assert "Vocabulary Practice Formats" in captured["system_instruction"]


async def test_lesson_message_skips_vocab_formats_for_daily_slots(
    client: AsyncClient, as_principal, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    async def _fake_stream_chat(*, system_instruction: str, history: list, **_kw):
        captured["system_instruction"] = system_instruction
        yield _lesson_turn_reply("Let's go.")

    monkeypatch.setattr("app.api.v1.chat.stream_chat", _fake_stream_chat)

    user_id = await _sync_user(client, as_principal, "clerk_lesson_vocab_daily")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Hi"}
    ) as resp:
        async for _chunk in resp.aiter_text():
            pass

    assert "Vocabulary Practice Formats" not in captured["system_instruction"]


async def test_lesson_message_emits_error_when_metadata_persist_fails(
    client: AsyncClient, as_principal, mock_gemini, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from app.api.v1 import chat as chat_mod

    async def _boom(*_a, **_k):
        raise SQLAlchemyError("simulated persist failure")

    monkeypatch.setattr(chat_mod, "_upsert_mistake", _boom)

    user_id = await _sync_user(client, as_principal, "clerk_lesson_persist_fail")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    mistakes = [
        {
            "pattern_type": "missing articles",
            "example_text": "I went to store yesterday",
            "correction": "I went to the store yesterday",
        }
    ]
    mock_gemini([_lesson_turn_reply("Let's fix that.", mistakes=mistakes)])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I went to store yesterday"},
    ) as resp:
        assert resp.status_code == 200
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    assert error_events[0][1]["code"] == "LESSON_PERSIST_FAILED"
    assert not any(e[0] == "done" for e in events)

    history_resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    assert [m["role"] for m in history_resp.json()["messages"]] == ["user"]
