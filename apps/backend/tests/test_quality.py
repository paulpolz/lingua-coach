"""Quality events API, finish CSAT, snapshots, and no-FK after chat delete."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.chat import ChatMessage, ChatSession
from app.models.enums import (
    ChatMessageRole,
    ChatSessionType,
    LearningGoalStatus,
    LearningPlanStatus,
    LessonStatus,
)
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.quality_event import QualityEvent
from app.models.user import User
from app.services.quality import should_sample_correction_turn
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LESSON_CURRICULUM

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


@pytest.fixture(autouse=True)
def _noop_report_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.lessons.update_reports_after_lesson", _noop)


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
    profile = Profile(
        user_id=uuid.UUID(user_id),
        native_language="en",
        target_language="es",
        target_level="A2",
        goal_outcome="Travel Spanish",
        target_plan_days=90,
        pace_window_hours=24,
        active_learning_plan_id=None,
    )
    db_session.add(profile)
    await db_session.flush()
    profile.active_learning_plan_id = plan.id
    await db_session.commit()


async def _seed_active_lesson(db_session, user_id: str) -> Lesson:
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=1,
        payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": None},
        status=LessonStatus.active,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)
    return lesson


async def _seed_lesson_chat(
    db_session, user_id: str, lesson: Lesson, *, assistant_content: str = "Hola, practica el pasado."
) -> tuple[ChatSession, ChatMessage]:
    session = ChatSession(
        user_id=uuid.UUID(user_id), type=ChatSessionType.lesson, lesson_id=lesson.id
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content="hi"))
    assistant = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.assistant,
        content=assistant_content,
        metadata_json={"corrections": [], "tips": [], "suggest_finish": False},
    )
    db_session.add(assistant)
    await db_session.commit()
    await db_session.refresh(assistant)
    return session, assistant


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


def test_should_sample_correction_turn_is_stable_by_message_id() -> None:
    assert should_sample_correction_turn(uuid.UUID(int=0)) is True
    assert should_sample_correction_turn(uuid.UUID(int=9)) is True
    assert should_sample_correction_turn(uuid.UUID(int=10)) is False
    assert should_sample_correction_turn(uuid.UUID(int=109)) is True


def test_judge_online_skips_without_api_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from app.config import settings
    from evals.judge_online import main

    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert main([]) == 0
    assert "GEMINI_API_KEY" in capsys.readouterr().out


async def test_quality_events_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "lesson_id": None,
            "value": {"thumb": 1},
        },
    )
    assert resp.status_code == 401


async def test_thumbs_copies_snapshot_when_message_exists(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_snapshot")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session, assistant = await _seed_lesson_chat(
        db_session, user_id, lesson, assistant_content="El pretérito es útil."
    )
    assistant_id = assistant.id
    session_id = session.id
    lesson_id = lesson.id

    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session_id),
            "message_id": str(assistant_id),
            "lesson_id": str(lesson_id),
            "value": {"thumb": 1},
        },
    )
    assert resp.status_code == 204

    db_session.expire_all()
    row = (
        await db_session.execute(select(QualityEvent).where(QualityEvent.user_id == uuid.UUID(user_id)))
    ).scalar_one()
    assert row.kind == "thumbs"
    assert row.surface == "lesson"
    assert row.message_id == assistant_id
    assert row.session_id == session_id
    assert row.value["thumb"] == 1
    snapshot = row.value["snapshot"]
    assert snapshot["assistant_text"] == "El pretérito es útil."
    assert snapshot["native"] == "en"
    assert snapshot["target"] == "es"
    assert snapshot["lesson_snippet"]["grammar_focus"] == VALID_LESSON_CURRICULUM["grammar_focus"]


async def test_thumbs_without_message_still_stores_event(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_gone_msg")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session, assistant = await _seed_lesson_chat(db_session, user_id, lesson)
    gone_id = assistant.id
    await db_session.delete(assistant)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session.id),
            "message_id": str(gone_id),
            "lesson_id": str(lesson.id),
            "value": {"thumb": -1},
        },
    )
    assert resp.status_code == 204

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "thumbs"
            )
        )
    ).scalar_one()
    assert row.message_id == gone_id
    assert "snapshot" not in row.value
    candidates = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "judge_candidate"
            )
        )
    ).scalars().all()
    assert candidates == []


async def test_thumbs_down_writes_judge_candidate_with_snapshot(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_thumbs_down")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session, assistant = await _seed_lesson_chat(db_session, user_id, lesson)

    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session.id),
            "message_id": str(assistant.id),
            "lesson_id": str(lesson.id),
            "value": {"thumb": -1},
        },
    )
    assert resp.status_code == 204

    db_session.expire_all()
    kinds = {
        row.kind
        for row in (
            await db_session.execute(select(QualityEvent).where(QualityEvent.user_id == uuid.UUID(user_id)))
        ).scalars().all()
    }
    assert kinds == {"thumbs", "judge_candidate"}
    candidate = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "judge_candidate"
            )
        )
    ).scalar_one()
    assert candidate.value["source"] == "thumbs_down"
    assert candidate.value["snapshot"]["assistant_text"]


async def test_thumbs_rejects_other_users_session(
    client: AsyncClient, as_principal, db_session
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_quality_owner")
    await _seed_onboarded_user(db_session, owner_id)
    lesson = await _seed_active_lesson(db_session, owner_id)
    session, assistant = await _seed_lesson_chat(db_session, owner_id, lesson)

    await _sync_user(client, as_principal, "clerk_quality_intruder")
    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session.id),
            "message_id": str(assistant.id),
            "lesson_id": str(lesson.id),
            "value": {"thumb": 1},
        },
    )
    assert resp.status_code == 404


async def test_finish_with_csat_writes_quality_event(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_finish_csat")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    await _seed_lesson_chat(db_session, user_id, lesson)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/finish",
        json={"learner_feedback": "too hard", "csat": 4},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    await db_session.refresh(lesson)
    assert lesson.payload["session_summary"]["learner_feedback"] == "too hard"
    row = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "lesson_csat"
            )
        )
    ).scalar_one()
    assert row.surface == "lesson"
    assert row.lesson_id == lesson.id
    assert row.value == {"csat": 4}


async def test_finish_without_csat_still_works(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_finish_no_csat")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish", json={})
    assert resp.status_code == 200

    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "lesson_csat"
            )
        )
    ).scalars().all()
    assert rows == []


async def test_quality_events_message_id_survives_chat_delete_on_finish(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_no_fk")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session, assistant = await _seed_lesson_chat(db_session, user_id, lesson)
    message_id = assistant.id
    session_id = session.id
    lesson_id = lesson.id

    thumbs = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session_id),
            "message_id": str(message_id),
            "lesson_id": str(lesson_id),
            "value": {"thumb": -1},
        },
    )
    assert thumbs.status_code == 204

    finish = await client.post(f"/api/v1/lessons/{lesson_id}/finish", json={"csat": 2})
    assert finish.status_code == 200

    db_session.expire_all()
    remaining_messages = (
        await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))
    ).scalars().all()
    assert remaining_messages == []
    assert await db_session.get(ChatSession, session_id) is None

    thumbs_row = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "thumbs"
            )
        )
    ).scalar_one()
    assert thumbs_row.message_id == message_id
    assert thumbs_row.session_id == session_id

    csat_row = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "lesson_csat"
            )
        )
    ).scalar_one()
    assert csat_row.value["csat"] == 2

    still_ok = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(session_id),
            "message_id": str(message_id),
            "lesson_id": str(lesson_id),
            "value": {"thumb": 1},
        },
    )
    assert still_ok.status_code == 204


async def test_sampled_correction_turn_writes_judge_candidate(
    client: AsyncClient, as_principal, mock_gemini, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.quality.should_sample_correction_turn", lambda _mid: True)
    user_id = await _sync_user(client, as_principal, "clerk_quality_sample")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session_id = (
        await client.post(
            "/api/v1/chat/sessions", json={"type": "lesson", "lesson_id": str(lesson.id)}
        )
    ).json()["id"]

    corrections = [
        {"span": "I goed", "correction": "I went", "type": "grammar", "note": "irregular past"}
    ]
    mock_gemini([_lesson_turn_reply("Sigue.", corrections=corrections)])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Yesterday I goed."},
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk
    assert resp.status_code == 200
    done = [e for e in _parse_sse(raw) if e[0] == "done"]
    assert len(done) == 1
    message_id = uuid.UUID(done[0][1]["message_id"])

    db_session.expire_all()
    candidate = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "judge_candidate"
            )
        )
    ).scalar_one()
    assert candidate.message_id == message_id
    assert candidate.value["source"] == "corrections_sample"
    assert "Sigue" in candidate.value["snapshot"]["assistant_text"]


async def test_csat_via_quality_endpoint(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_quality_csat_post")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)

    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "lesson_csat",
            "surface": "lesson",
            "session_id": None,
            "message_id": None,
            "lesson_id": str(lesson.id),
            "value": {"csat": 5},
        },
    )
    assert resp.status_code == 204
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(QualityEvent).where(
                QualityEvent.user_id == uuid.UUID(user_id), QualityEvent.kind == "lesson_csat"
            )
        )
    ).scalar_one()
    assert row.value == {"csat": 5}


async def test_invalid_thumb_is_422(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_quality_bad_thumb")
    resp = await client.post(
        "/api/v1/quality/events",
        json={
            "kind": "thumbs",
            "surface": "lesson",
            "session_id": str(uuid.uuid4()),
            "value": {"thumb": 0},
        },
    )
    assert resp.status_code == 422
