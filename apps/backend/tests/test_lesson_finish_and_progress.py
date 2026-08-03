"""`POST /lessons/{id}/finish` + `GET /progress` — docs/implementation-readiness.md
§6 ("Finish lesson", "GET /progress"), docs/tech_requirements/backend.md
"Plan schedule and pacing" (24h on-pace window, slip reschedule), and
database.md "Chat" retention rules (delete lesson chat on finish).

§14 smoke test #10 ("Finish after 24h (or mocked clock) -> plan_slip_days
increments") is exercised here by backdating `started_at` directly via the
`db_session` fixture rather than a fake clock API — see
`test_finish_with_backdated_started_at_increments_slip_and_reschedules`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

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
from app.models.progress_event import ProgressEvent
from app.models.user import User
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LESSON_CURRICULUM


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def _seed_onboarded_user(
    db_session, user_id: str, *, target_plan_days: int = 90, pace_window_hours: int = 24
) -> None:
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
        target_plan_days=target_plan_days,
        pace_window_hours=pace_window_hours,
        active_learning_plan_id=None,
    )
    db_session.add(profile)
    await db_session.flush()
    profile.active_learning_plan_id = plan.id
    await db_session.commit()


async def _seed_active_lesson(
    db_session, user_id: str, *, lesson_number: int = 1, started_at: datetime | None = None
) -> Lesson:
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=lesson_number,
        payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": None},
        status=LessonStatus.active,
        started_at=started_at or datetime.now(timezone.utc),
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)
    return lesson


async def _seed_lesson_chat_session(
    db_session, user_id: str, lesson: Lesson, *, suggest_finish: bool = False
) -> ChatSession:
    session = ChatSession(
        user_id=uuid.UUID(user_id), type=ChatSessionType.lesson, lesson_id=lesson.id
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content="hi"))
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.assistant,
            content="Let's get started",
            metadata_json={
                "corrections": [],
                "tips": [],
                "plan_updates": None,
                "suggest_finish": suggest_finish,
                "course_roadmap_draft": None,
            },
        )
    )
    await db_session.commit()
    return session


# ---------------------------------------------------------------------------
# POST /lessons/{id}/finish
# ---------------------------------------------------------------------------


async def test_finish_requires_onboarding_complete(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_finish_gate")
    resp = await client.post(f"/api/v1/lessons/{uuid.uuid4()}/finish")
    assert resp.status_code == 403
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_finish_returns_404_for_unowned_lesson(client: AsyncClient, as_principal, db_session) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_finish_owner")
    await _seed_onboarded_user(db_session, owner_id)
    lesson = await _seed_active_lesson(db_session, owner_id)

    intruder_id = await _sync_user(client, as_principal, "clerk_finish_intruder")
    await _seed_onboarded_user(db_session, intruder_id)
    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_finish_returns_409_when_lesson_not_active(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_not_active")
    await _seed_onboarded_user(db_session, user_id)
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=1,
        payload={},
        status=LessonStatus.generating,
    )
    db_session.add(lesson)
    await db_session.commit()

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 409
    assert resp.json()["code"] == "LESSON_NOT_ACTIVE"


async def test_finish_happy_path_on_pace_no_slip(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_on_pace")
    await _seed_onboarded_user(db_session, user_id, target_plan_days=90)
    lesson = await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    await _seed_lesson_chat_session(db_session, user_id, lesson, suggest_finish=True)

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"status", "accomplished_at", "pace_status", "schedule_updated"}
    assert body["status"] == "accomplished"
    assert body["pace_status"] == "on_pace"
    assert body["schedule_updated"] is False
    assert body["accomplished_at"] is not None

    await db_session.refresh(lesson)
    assert lesson.status == LessonStatus.accomplished
    assert lesson.pace_status.value == "on_pace"
    assert lesson.accomplished_at is not None
    summary = lesson.payload["session_summary"]
    assert summary["exit_criteria_met"] is True
    assert set(summary["completed_slots"]) == {"warmup", "production"}
    assert summary["deferred_items"] == []
    # curriculum must survive the payload merge untouched.
    assert lesson.payload["curriculum"]["lesson_goal"] == VALID_LESSON_CURRICULUM["lesson_goal"]

    profile_result = await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    profile = profile_result.scalar_one()
    assert profile.plan_slip_days == 0

    events_result = await db_session.execute(
        select(ProgressEvent).where(ProgressEvent.user_id == uuid.UUID(user_id))
    )
    event_types = {e.event_type for e in events_result.scalars().all()}
    assert "lesson_completed" in event_types
    assert "plan_rescheduled" not in event_types


async def test_finish_early_without_suggest_finish_has_empty_completed_slots(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_early")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    await _seed_lesson_chat_session(db_session, user_id, lesson, suggest_finish=False)

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 200

    await db_session.refresh(lesson)
    summary = lesson.payload["session_summary"]
    assert summary["completed_slots"] == []
    assert summary["exit_criteria_met"] is False
    assert {d["slot_id"] for d in summary["deferred_items"]} == {"warmup", "production"}


async def test_finish_accepts_explicit_completed_slot_ids_body(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_explicit_slots")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    # No chat session at all — empty POST should still work; the request
    # body should be authoritative when provided.
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/finish",
        json={"completed_slot_ids": ["warmup"], "learner_feedback": "wants more speaking"},
    )
    assert resp.status_code == 200

    await db_session.refresh(lesson)
    summary = lesson.payload["session_summary"]
    assert summary["completed_slots"] == ["warmup"]
    assert summary["exit_criteria_met"] is False
    assert summary["learner_feedback"] == "wants more speaking"


async def test_finish_with_empty_body_works(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_empty_body")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish", json={})
    assert resp.status_code == 200


async def test_finish_with_backdated_started_at_increments_slip_and_reschedules(
    client: AsyncClient, as_principal, db_session
) -> None:
    """§14 smoke test #10 — instead of waiting 24h (or a fake clock API),
    backdate `started_at` directly, which naturally exercises the same
    elapsed-time computation `compute_lesson_pace_status` uses at finish."""
    user_id = await _sync_user(client, as_principal, "clerk_finish_slip")
    await _seed_onboarded_user(db_session, user_id, target_plan_days=10, pace_window_hours=24)
    lesson = await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=30)
    )

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pace_status"] == "slipped"
    assert body["schedule_updated"] is True

    profile_result = await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    profile = profile_result.scalar_one()
    assert profile.plan_slip_days == 1
    assert profile.projected_completion_at is not None
    # remaining_plan_days = target(10) - plan_days_done(1) = 9 -> +9*24h
    expected_min = datetime.now(timezone.utc) + timedelta(hours=9 * 24) - timedelta(minutes=1)
    assert profile.projected_completion_at > expected_min

    events_result = await db_session.execute(
        select(ProgressEvent).where(ProgressEvent.user_id == uuid.UUID(user_id))
    )
    event_types = {e.event_type for e in events_result.scalars().all()}
    assert "plan_rescheduled" in event_types
    assert "lesson_completed" in event_types


async def test_finish_deletes_lesson_chat_session_and_messages(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_chat_deletion")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id)
    session = await _seed_lesson_chat_session(db_session, user_id, lesson, suggest_finish=True)
    session_id = session.id

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 200

    # The finish request ran on a separate `AsyncSession` (the `client`
    # fixture's own session-per-request), so `db_session`'s identity map
    # still holds pre-delete copies of these rows — expire them to force a
    # fresh read from the DB rather than asserting against stale cache.
    db_session.expire_all()

    remaining_messages = await db_session.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    assert remaining_messages.scalars().all() == []
    remaining_session = await db_session.get(ChatSession, session_id)
    assert remaining_session is None


async def test_finish_then_start_next_lesson_is_not_blocked(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_finish_then_start")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _seed_active_lesson(db_session, user_id, lesson_number=1)

    finish_resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert finish_resp.status_code == 200

    mock_generate_json([json.dumps(VALID_LESSON_CURRICULUM)])
    start_resp = await client.post("/api/v1/lessons/start")
    assert start_resp.status_code == 202
    assert start_resp.json()["lesson_number"] == 2


# ---------------------------------------------------------------------------
# GET /progress
# ---------------------------------------------------------------------------


async def test_progress_requires_onboarding_complete(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_progress_gate")
    resp = await client.get("/api/v1/progress")
    assert resp.status_code == 403


async def test_progress_shape_without_active_lesson(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_progress_no_active")
    await _seed_onboarded_user(db_session, user_id, target_plan_days=90)

    resp = await client.get("/api/v1/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "plan_days_done",
        "target_plan_days",
        "plan_slip_days",
        "projected_completion_at",
        "pace_summary",
        "active_lesson",
    }
    assert body["plan_days_done"] == 0
    assert body["target_plan_days"] == 90
    assert body["active_lesson"] is None
    assert body["pace_summary"] == "not_started"


async def test_progress_shape_with_active_lesson(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_progress_active")
    await _seed_onboarded_user(db_session, user_id, pace_window_hours=24)
    lesson = await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=5)
    )

    resp = await client.get("/api/v1/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_lesson"] is not None
    assert body["active_lesson"]["id"] == str(lesson.id)
    assert body["active_lesson"]["lesson_number"] == 1
    assert body["active_lesson"]["hours_remaining_in_pace_window"] == pytest.approx(19, abs=0.2)


async def test_progress_active_lesson_overdue_shows_negative_hours_remaining_and_behind(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_progress_overdue")
    await _seed_onboarded_user(db_session, user_id, pace_window_hours=24)
    await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=30)
    )

    resp = await client.get("/api/v1/progress")
    body = resp.json()
    assert body["active_lesson"]["hours_remaining_in_pace_window"] < 0
    assert body["pace_summary"] == "behind"


# ---------------------------------------------------------------------------
# GET /profile pace_summary transitions
# ---------------------------------------------------------------------------


async def test_profile_pace_summary_not_started_then_behind_when_lesson_overdue(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_profile_pace_transitions")
    await _seed_onboarded_user(db_session, user_id, pace_window_hours=24)

    not_started_resp = await client.get("/api/v1/profile")
    assert not_started_resp.json()["schedule"]["pace_summary"] == "not_started"

    await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=30)
    )

    behind_resp = await client.get("/api/v1/profile")
    assert behind_resp.json()["schedule"]["pace_summary"] == "behind"


async def test_profile_pace_summary_on_pace_when_active_lesson_within_window(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_profile_pace_on_pace")
    await _seed_onboarded_user(db_session, user_id, pace_window_hours=24)
    await _seed_active_lesson(
        db_session, user_id, started_at=datetime.now(timezone.utc) - timedelta(hours=3)
    )

    resp = await client.get("/api/v1/profile")
    assert resp.json()["schedule"]["pace_summary"] == "on_pace"
