"""`GET /api/v1/profile` shape — docs/implementation-readiness.md §6."""

from __future__ import annotations

from httpx import AsyncClient

from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LEARNER_PROFILE


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def test_profile_before_onboarding_returns_empty_shape(
    client: AsyncClient, as_principal
) -> None:
    await _sync_user(client, as_principal, "clerk_profile_empty")
    resp = await client.get("/api/v1/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_summary"] is None
    assert body["level"] is None
    assert body["native_language"] is None
    assert body["target_language"] is None
    assert body["time_budget"] is None
    assert body["topics"] == []
    assert body["vocab_priorities"] == []
    assert body["grammar_mastery"] == {}
    assert body["schedule"]["pace_summary"] == "not_started"
    assert body["schedule"]["target_plan_days"] is None
    assert body["schedule"]["plan_days_done"] == 0
    assert body["schedule"]["pace_window_hours"] == 24


async def test_profile_after_interview_reflects_persisted_fields(
    client: AsyncClient, as_principal, mock_gemini
) -> None:
    import json

    await _sync_user(client, as_principal, "clerk_profile_after_interview")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    reply = "Got it!\n\n```json:learner_profile\n" + json.dumps(VALID_LEARNER_PROFILE) + "\n```"
    mock_gemini([reply])
    async with client.stream(
        "POST", f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "my situation"}
    ) as resp:
        async for _ in resp.aiter_text():
            pass

    profile_resp = await client.get("/api/v1/profile")
    body = profile_resp.json()
    assert body["goal_summary"] == VALID_LEARNER_PROFILE["goal"]["outcome"]
    assert body["level"] == VALID_LEARNER_PROFILE["level"]["self_assessed"]
    assert body["native_language"] == VALID_LEARNER_PROFILE["languages"]["native"]
    assert body["target_language"] == VALID_LEARNER_PROFILE["languages"]["target"]
    assert "english_level" not in body
    assert body["time_budget"]["minutes_per_session"] == 60
    assert body["time_budget"]["sessions_per_week"] == 5
    # "sustainable" (skill-file example value) normalizes to the readiness §8 enum.
    assert body["time_budget"]["intensity"] == "moderate"
    assert body["topics"] == VALID_LEARNER_PROFILE["focus"]["topic_priorities"]
    assert body["vocab_priorities"] == VALID_LEARNER_PROFILE["focus"]["vocab_priorities"]
    assert body["schedule"]["pace_summary"] == "not_started"


async def test_profile_after_accept_includes_schedule(
    client: AsyncClient, as_principal, db_session
) -> None:
    import uuid

    from app.models.chat import ChatMessage, ChatSession
    from app.models.enums import ChatMessageRole, ChatSessionType, LearningGoalStatus
    from app.models.learning_goal import LearningGoal

    user_id = await _sync_user(client, as_principal, "clerk_profile_after_accept")

    goal = LearningGoal(
        user_id=uuid.UUID(user_id), goal_statement="test goal", status=LearningGoalStatus.draft
    )
    session = ChatSession(id=uuid.uuid4(), user_id=uuid.UUID(user_id), type=ChatSessionType.onboarding)
    db_session.add_all([goal, session])
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content="hi"))
    await db_session.commit()

    accept_resp = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": str(session.id), "course_roadmap": VALID_COURSE_ROADMAP},
    )
    assert accept_resp.status_code == 200

    profile_resp = await client.get("/api/v1/profile")
    schedule = profile_resp.json()["schedule"]
    assert schedule["target_plan_days"] == 90
    assert schedule["projected_completion_at"] is not None
    assert schedule["pace_summary"] == "not_started"
    assert schedule["plan_days_done"] == 0
