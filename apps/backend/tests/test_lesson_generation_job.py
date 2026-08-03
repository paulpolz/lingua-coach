"""In-process lesson generation job — status transitions (`pending` ->
`running` -> `done`|`failed`), the one-repair-retry rule (ai-api.md
"Structured lesson output"), and the resulting `GET /jobs/{id}` /
`GET /lessons/{id}` / `GET /lessons/active` shapes (readiness §6). Gemini is
always mocked (`mock_generate_json` / `mock_generate_json_error`) — never a
real network call."""

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


async def test_successful_generation_transitions_job_done_and_lesson_active(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_job_success")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json([json.dumps(VALID_LESSON_CURRICULUM)])

    start_resp = await client.post("/api/v1/lessons/start")
    assert start_resp.status_code == 202
    ids = start_resp.json()

    job_resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    assert job_resp.status_code == 200
    job_body = job_resp.json()
    assert set(job_body.keys()) == {
        "id", "status", "type", "result_ref", "error", "created_at", "updated_at"
    }
    assert job_body["status"] == "done"
    assert job_body["type"] == "lesson_generate"
    assert job_body["result_ref"] == ids["lesson_id"]
    assert job_body["error"] is None

    lesson_resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}")
    assert lesson_resp.status_code == 200
    lesson_body = lesson_resp.json()
    assert set(lesson_body.keys()) == {
        "id", "lesson_number", "status", "started_at", "accomplished_at", "pace_status", "payload"
    }
    assert lesson_body["status"] == "active"
    assert lesson_body["started_at"] is not None
    assert lesson_body["accomplished_at"] is None
    assert lesson_body["payload"]["version"] == 1
    assert lesson_body["payload"]["curriculum"]["lesson_goal"] == VALID_LESSON_CURRICULUM["lesson_goal"]
    assert lesson_body["payload"]["session_summary"] is None

    active_resp = await client.get("/api/v1/lessons/active")
    assert active_resp.status_code == 200
    assert active_resp.json()["id"] == ids["lesson_id"]


async def test_invalid_json_is_repaired_on_retry_and_job_succeeds(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_job_repair_success")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json(["not valid json at all", json.dumps(VALID_LESSON_CURRICULUM)])

    start_resp = await client.post("/api/v1/lessons/start")
    ids = start_resp.json()

    job_resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    assert job_resp.json()["status"] == "done"

    lesson_resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}")
    assert lesson_resp.json()["status"] == "active"


async def test_invalid_json_twice_fails_job_and_lesson(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_job_fail_twice")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json(["still not json", "also not json"])

    start_resp = await client.post("/api/v1/lessons/start")
    ids = start_resp.json()

    job_resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    job_body = job_resp.json()
    assert job_body["status"] == "failed"
    assert job_body["error"] is not None
    assert job_body["result_ref"] is None

    lesson_resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}")
    assert lesson_resp.json()["status"] == "failed"

    # A failed lesson does not count as generating/active — the user can
    # retry (backend.md "Job failure ... user retries POST /lessons/start").
    active_resp = await client.get("/api/v1/lessons/active")
    assert active_resp.json() is None

    retry_resp = await client.post("/api/v1/lessons/start")
    assert retry_resp.status_code != 409


async def test_schema_invalid_response_twice_fails_job(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    """Syntactically valid JSON that fails `LessonCurriculum` validation
    (missing required fields) should also trigger the repair path and fail
    the job if the retry is equally invalid."""
    user_id = await _sync_user(client, as_principal, "clerk_job_schema_invalid")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json([json.dumps({"lesson_goal": "too little"}), json.dumps({"still": "wrong"})])

    start_resp = await client.post("/api/v1/lessons/start")
    ids = start_resp.json()

    job_resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    assert job_resp.json()["status"] == "failed"


async def test_gemini_failure_fails_job_immediately_without_retry(
    client: AsyncClient, as_principal, db_session, mock_generate_json_error
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_job_gemini_error")
    await _seed_onboarded_user(db_session, user_id)
    mock_generate_json_error("simulated Gemini timeout")

    start_resp = await client.post("/api/v1/lessons/start")
    ids = start_resp.json()

    job_resp = await client.get(f"/api/v1/jobs/{ids['job_id']}")
    job_body = job_resp.json()
    assert job_body["status"] == "failed"
    assert "simulated Gemini timeout" in job_body["error"]

    lesson_resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}")
    assert lesson_resp.json()["status"] == "failed"


async def test_active_lesson_is_null_when_none_exists(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_no_active_lesson")
    await _seed_onboarded_user(db_session, user_id)

    resp = await client.get("/api/v1/lessons/active")
    assert resp.status_code == 200
    assert resp.json() is None
