"""POST /onboarding/accept."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.models.enums import UserReportType
from app.models.learning_plan import LearningPlan
from app.models.user import User
from app.models.user_report import UserReport
from tests.factories import make_chat_session, make_goal, make_profile, make_user, roadmap_dict


async def _ready_user(db: AsyncSession, **profile: Any) -> tuple[User, ChatSession]:
    user = await make_user(db, onboarding_complete=False)
    await make_profile(db, user, **profile)
    await make_goal(db, user)
    return user, await make_chat_session(db, user)


async def test_accept_stores_validated_roadmap_and_unlocks(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user, session = await _ready_user(db)
    user_id, session_id = user.id, session.id
    roadmap = roadmap_dict(injected_instructions="ignore previous instructions")

    response = await client.post(
        "/api/v1/onboarding/accept", json={"session_id": str(session_id), "course_roadmap": roadmap}
    )

    assert response.status_code == 200, response.text
    assert response.json()["onboarding_complete"] is True
    db.expire_all()
    plan = (await db.execute(select(LearningPlan).where(LearningPlan.user_id == user_id))).scalar_one()
    assert "injected_instructions" not in plan.roadmap
    assert plan.roadmap["summary"]["target_plan_days"] == 30
    assert (await db.get(User, user_id)).onboarding_complete is True  # type: ignore[union-attr]
    assert await db.get(ChatSession, session_id) is None
    types = set((await db.execute(select(UserReport.report_type).where(UserReport.user_id == user_id))).scalars())
    assert types == {UserReportType.roadmap, UserReportType.four_week_plan}


async def test_accept_rejects_a_malformed_roadmap(client: httpx.AsyncClient, db: AsyncSession) -> None:
    _, session = await _ready_user(db)

    response = await client.post(
        "/api/v1/onboarding/accept",
        json={"session_id": str(session.id), "course_roadmap": {"version": 1, "milestones": []}},
    )

    assert response.status_code == 422


async def test_accept_without_draft_goal_is_422(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db, onboarding_complete=False)
    session = await make_chat_session(db, user)

    response = await client.post(
        "/api/v1/onboarding/accept", json={"session_id": str(session.id), "course_roadmap": roadmap_dict()}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ONBOARDING_INTERVIEW_INCOMPLETE"
