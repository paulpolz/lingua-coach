"""`POST /api/v1/onboarding/accept` — Pydantic validation + full persistence
sequence per database.md "Onboarding data flow"."""

from __future__ import annotations

import copy
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatMessageRole, ChatSessionType, LearningGoalStatus, UserReportType
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
from tests.fixtures import VALID_COURSE_ROADMAP


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


async def _seed_completed_interview(db_session, user_id: str) -> str:
    """Mimic the state after onboarding chat has persisted a learner_profile:
    a draft `learning_goals` row + an onboarding `chat_session` to accept."""
    goal = LearningGoal(
        user_id=uuid.UUID(user_id),
        goal_statement="Speak confidently in daily work meetings",
        horizon="6 months",
        success_criteria=["Can lead a 15-minute status update unscripted"],
        status=LearningGoalStatus.draft,
    )
    session = ChatSession(id=uuid.uuid4(), user_id=uuid.UUID(user_id), type=ChatSessionType.onboarding)
    db_session.add_all([goal, session])
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content="hi"))
    await db_session.commit()
    return str(session.id)


async def test_accept_rejects_invalid_roadmap_shape(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_accept_invalid")
    bad_roadmap = copy.deepcopy(VALID_COURSE_ROADMAP)
    bad_roadmap["milestones"] = []  # violates min_length=1

    resp = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": str(uuid.uuid4()), "course_roadmap": bad_roadmap},
    )
    assert resp.status_code == 422


async def test_accept_without_draft_goal_returns_422(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_accept_no_goal")
    # A real (owned) onboarding session exists, but no learner_profile /
    # draft goal was ever persisted from it — the interview never completed.
    session_resp = await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})
    session_id = session_resp.json()["id"]

    resp = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": session_id, "course_roadmap": VALID_COURSE_ROADMAP},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "ONBOARDING_INTERVIEW_INCOMPLETE"


async def test_accept_unknown_session_returns_404(client: AsyncClient, as_principal, db_session) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_accept_404")
    await _seed_completed_interview(db_session, user_id)

    resp = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": str(uuid.uuid4()), "course_roadmap": VALID_COURSE_ROADMAP},
    )
    assert resp.status_code == 404


async def test_accept_full_flow_persists_plan_and_unlocks_onboarding(
    client: AsyncClient, as_principal, db_session
) -> None:
    clerk_id = "clerk_accept_happy_path"
    user_id = await _sync_user(client, as_principal, clerk_id)
    session_id = await _seed_completed_interview(db_session, user_id)

    resp = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": session_id, "course_roadmap": VALID_COURSE_ROADMAP},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarding_complete"] is True
    assert body["plan_accepted_at"]

    user = (
        await db_session.execute(select(User).where(User.clerk_user_id == clerk_id))
    ).scalar_one()
    assert user.onboarding_complete is True
    assert user.plan_accepted_at is not None

    plan = (
        await db_session.execute(select(LearningPlan).where(LearningPlan.user_id == user.id))
    ).scalar_one()
    assert plan.roadmap["summary"]["target_plan_days"] == 90
    assert plan.roadmap["summary"]["target_language"] == "en"
    assert plan.roadmap["summary"]["native_language"] == "en"
    assert plan.status.value == "accepted"

    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert profile.target_plan_days == 90
    assert profile.active_learning_plan_id == plan.id
    assert profile.projected_completion_at is not None

    goal = (
        await db_session.execute(select(LearningGoal).where(LearningGoal.user_id == user.id))
    ).scalar_one()
    assert goal.status == LearningGoalStatus.active

    # Onboarding chat transcript + session deleted per database.md retention rules.
    remaining_session = (
        await db_session.execute(select(ChatSession).where(ChatSession.id == uuid.UUID(session_id)))
    ).scalar_one_or_none()
    assert remaining_session is None
    remaining_messages = (
        await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id)))
    ).scalars().all()
    assert remaining_messages == []

    reports = (
        await db_session.execute(select(UserReport).where(UserReport.user_id == user.id))
    ).scalars().all()
    types = {row.report_type for row in reports}
    assert types == {UserReportType.roadmap, UserReportType.four_week_plan}
    roadmap_body = next(row.body for row in reports if row.report_type == UserReportType.roadmap)
    assert "Roadmap" in roadmap_body
    assert "<!-- section:milestones -->" in roadmap_body
