from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import LearningGoalStatus, LearningPlanStatus, LessonStatus, UserReportType
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
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
    profile = Profile(
        user_id=uuid.UUID(user_id),
        target_plan_days=90,
        pace_window_hours=24,
        active_learning_plan_id=None,
    )
    db_session.add(profile)
    await db_session.flush()
    profile.active_learning_plan_id = plan.id
    await db_session.commit()


async def test_get_report_empty_before_first_lesson(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_report_empty")
    await _seed_onboarded_user(db_session, user_id)
    resp = await client.get("/api/v1/reports/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_type"] == "progress"
    assert body["body"] is None


async def test_get_report_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/reports/progress")
    assert resp.status_code == 401


async def test_get_report_requires_onboarding(client: AsyncClient, as_principal) -> None:
    await _sync_user(client, as_principal, "clerk_report_gate")
    resp = await client.get("/api/v1/reports/roadmap")
    assert resp.status_code == 403


async def test_finish_lesson_applies_report_ops(
    client: AsyncClient, as_principal, db_session, mock_generate_json
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_report_finish")
    await _seed_onboarded_user(db_session, user_id)
    lesson = Lesson(
        user_id=uuid.UUID(user_id),
        lesson_number=1,
        payload={"version": 1, "curriculum": VALID_LESSON_CURRICULUM, "session_summary": None},
        status=LessonStatus.active,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(lesson)
    await db_session.commit()

    ops = {
        "ops": [
            {
                "report_type": "progress",
                "op": "append_entry",
                "section_id": "update_log",
                "markdown": "## 2026-08-23\nPracticed past simple in standup stories.",
            },
            {
                "report_type": "progress",
                "op": "patch_section",
                "section_id": "latest_session",
                "markdown": "**This session:** articles still slip under speed.",
            },
        ]
    }
    mock_generate_json([json.dumps(ops)])

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/finish")
    assert resp.status_code == 200

    report_resp = await client.get("/api/v1/reports/progress")
    assert report_resp.status_code == 200
    markdown = report_resp.json()["body"]
    assert markdown is not None
    assert "articles still slip" in markdown
    assert "standup stories" in markdown

    row = (
        await db_session.execute(
            select(UserReport).where(
                UserReport.user_id == uuid.UUID(user_id),
                UserReport.report_type == UserReportType.progress,
            )
        )
    ).scalar_one()
    assert "<!-- section:update_log -->" in row.body
