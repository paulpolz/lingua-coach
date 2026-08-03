"""`POST /api/v1/lessons/start` — onboarding gate, `lesson_number` sequencing
(database.md "Lesson sequencing rules"), the `409 ACTIVE_LESSON_EXISTS`
conflict (readiness §6), and rate limiting. Gemini is always mocked via
`mock_generate_json` — the background job runs synchronously within the
test's `client.post(...)` call (Starlette runs `BackgroundTasks` before the
ASGI response completes)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.enums import LearningGoalStatus, LearningPlanStatus, LessonStatus
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.user import User
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LESSON_CURRICULUM


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def _seed_onboarded_user(db_session, user_id: str) -> None:
    """Mark onboarding complete + attach an accepted plan directly (bypassing
    the full onboarding chat flow, which is out of this phase's scope)."""
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


def _curriculum_reply(curriculum: dict) -> str:
    import json

    return json.dumps(curriculum)


async def test_start_lesson_requires_onboarding_complete(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_lesson_gate")
    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 403
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_start_lesson_happy_path_returns_202_and_sequences_from_one(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_start_1")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json([_curriculum_reply(VALID_LESSON_CURRICULUM)])

    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 202
    body = resp.json()
    assert set(body.keys()) == {"job_id", "lesson_id", "lesson_number"}
    assert body["lesson_number"] == 1
    uuid.UUID(body["job_id"])
    uuid.UUID(body["lesson_id"])


async def test_start_lesson_returns_409_when_generating_lesson_exists(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_409")
    await _seed_onboarded_user(db_session, user_id)

    existing = Lesson(
        user_id=uuid.UUID(user_id), lesson_number=1, payload={}, status=LessonStatus.generating
    )
    db_session.add(existing)
    await db_session.commit()

    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "ACTIVE_LESSON_EXISTS"
    assert body["active_lesson_id"] == str(existing.id)


async def test_start_lesson_returns_409_when_active_lesson_exists(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_409_active")
    await _seed_onboarded_user(db_session, user_id)

    existing = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=1,
        payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": None},
        status=LessonStatus.active,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(existing)
    await db_session.commit()

    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 409
    assert resp.json()["code"] == "ACTIVE_LESSON_EXISTS"


async def test_start_lesson_numbers_sequentially_after_accomplished(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_seq")
    await _seed_onboarded_user(db_session, user_id)

    for n in (1, 2, 3):
        db_session.add(
            Lesson(
                user_id=uuid.UUID(user_id),
                lesson_number=n,
                payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": {}},
                status=LessonStatus.accomplished,
                started_at=datetime.now(timezone.utc),
                accomplished_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()

    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 202
    assert resp.json()["lesson_number"] == 4


async def test_start_lesson_enforces_daily_rate_limit(
    client: AsyncClient, as_principal, db_session, mock_generate_json, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.services import rate_limit

    monkeypatch.setattr(settings, "lesson_start_rate_limit_per_day", 1)
    rate_limit.reset()

    user_id = await _sync_user(client, as_principal, "clerk_lesson_rate_limited")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json([_curriculum_reply(VALID_LESSON_CURRICULUM), _curriculum_reply(VALID_LESSON_CURRICULUM)])

    first = await client.post("/api/v1/lessons/start")
    assert first.status_code == 202

    # Finish the first lesson so the second attempt fails on rate limit, not
    # on the (unrelated) 409 active-lesson guard.
    lesson_id = uuid.UUID(first.json()["lesson_id"])
    lesson = await db_session.get(Lesson, lesson_id)
    lesson.status = LessonStatus.accomplished
    await db_session.commit()

    second = await client.post("/api/v1/lessons/start")
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMIT_EXCEEDED"
    rate_limit.reset()
