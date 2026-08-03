"""`POST /api/v1/lessons/{lesson_id}/stop` — docs/implementation-readiness.md
§6 (`204`) and backend.md "Lesson lifecycle" ("Stop": leave chat, lesson
stays `active`, resumable; no status change)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import LearningGoalStatus, LearningPlanStatus, LessonStatus
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
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


async def _create_active_lesson(db_session, user_id: str) -> Lesson:
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


async def test_stop_lesson_returns_404_for_unknown_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_stop_unknown")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.post(f"/api/v1/lessons/{uuid.uuid4()}/stop")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_stop_lesson_returns_404_for_malformed_id(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_stop_malformed")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.post("/api/v1/lessons/not-a-uuid/stop")
    assert resp.status_code == 404


async def test_stop_lesson_returns_404_for_other_users_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_stop_owner")
    await _seed_onboarded_user(db_session, owner_id)
    lesson = await _create_active_lesson(db_session, owner_id)

    intruder_id = await _sync_user(client, as_principal, "clerk_stop_intruder")
    await _seed_onboarded_user(db_session, intruder_id)
    resp = await client.post(f"/api/v1/lessons/{lesson.id}/stop")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_stop_lesson_requires_onboarding_complete(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_stop_gate")
    resp = await client.post(f"/api/v1/lessons/{uuid.uuid4()}/stop")
    assert resp.status_code == 403
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_stop_lesson_returns_204_and_leaves_lesson_active(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_stop_happy")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/stop")
    assert resp.status_code == 204
    assert resp.content == b""

    await db_session.refresh(lesson)
    assert lesson.status == LessonStatus.active
    assert lesson.accomplished_at is None


async def test_stop_lesson_is_callable_multiple_times(
    client: AsyncClient, as_principal, db_session
) -> None:
    """Stop is a UI-convenience signal, not a state transition — calling it
    more than once (e.g. resume then leave again) must not error."""
    user_id = await _sync_user(client, as_principal, "clerk_stop_repeat")
    await _seed_onboarded_user(db_session, user_id)
    lesson = await _create_active_lesson(db_session, user_id)

    first = await client.post(f"/api/v1/lessons/{lesson.id}/stop")
    second = await client.post(f"/api/v1/lessons/{lesson.id}/stop")
    assert first.status_code == 204
    assert second.status_code == 204

    events_result = await db_session.execute(
        select(ProgressEvent).where(ProgressEvent.lesson_id == lesson.id)
    )
    events = events_result.scalars().all()
    assert len(events) == 2
    assert all(e.event_type == "lesson_chat_stopped" for e in events)
