"""Ownership `404`s for `GET /api/v1/jobs/{job_id}` and
`GET /api/v1/lessons/{lesson_id}` — docs/implementation-readiness.md §6
("404 | Resource not found or not owned by user")."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient

from app.models.enums import LearningGoalStatus, LearningPlanStatus
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
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


async def _start_lesson(client: AsyncClient, mock_generate_json) -> dict:
    mock_generate_json([json.dumps(VALID_LESSON_CURRICULUM)])
    resp = await client.post("/api/v1/lessons/start")
    assert resp.status_code == 202
    return resp.json()


async def test_get_job_returns_404_for_unknown_id(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_job_unknown")
    resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_get_job_returns_404_for_malformed_id(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_job_malformed")
    resp = await client.get("/api/v1/jobs/not-a-uuid")
    assert resp.status_code == 404


async def test_get_job_returns_404_for_other_users_job(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_job_owner")
    await _seed_onboarded_user(db_session, owner_id)
    ids = await _start_lesson(client, mock_generate_json)

    await _sync_user(client, as_principal, "clerk_job_intruder")
    resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_get_lesson_returns_404_for_unknown_id(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_unknown")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.get(f"/api/v1/lessons/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_get_lesson_returns_404_for_malformed_id(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_malformed")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.get("/api/v1/lessons/not-a-uuid")
    assert resp.status_code == 404


async def test_get_lesson_returns_404_for_other_users_lesson(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    owner_id = await _sync_user(client, as_principal, "clerk_lesson_owner")
    await _seed_onboarded_user(db_session, owner_id)
    ids = await _start_lesson(client, mock_generate_json)

    intruder_id = await _sync_user(client, as_principal, "clerk_lesson_intruder")
    await _seed_onboarded_user(db_session, intruder_id)
    resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_lessons_active_and_lesson_id_routes_require_onboarding_complete(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_lesson_routes_gate")
    active_resp = await client.get("/api/v1/lessons/active")
    assert active_resp.status_code == 403
    lesson_resp = await client.get(f"/api/v1/lessons/{uuid.uuid4()}")
    assert lesson_resp.status_code == 403
