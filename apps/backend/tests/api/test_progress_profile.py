"""GET /progress and GET /profile share one pace snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LessonStatus, PaceStatus
from tests.factories import make_lesson, make_profile, make_user


async def test_progress_and_profile_agree_on_pace(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await make_profile(db, user, pace_window_hours=24, target_plan_days=30, plan_slip_days=1)
    now = datetime.now(UTC)
    done = await make_lesson(
        db, user, status=LessonStatus.accomplished, lesson_number=1, started_at=now - timedelta(hours=30)
    )
    done.accomplished_at, done.pace_status = now - timedelta(hours=1), PaceStatus.slipped
    active = await make_lesson(db, user, lesson_number=2, started_at=now - timedelta(hours=2))
    await db.flush()

    progress = (await client.get("/api/v1/progress")).json()
    profile = (await client.get("/api/v1/profile")).json()

    assert progress["plan_days_done"] == profile["schedule"]["plan_days_done"] == 1
    assert progress["pace_summary"] == profile["schedule"]["pace_summary"] == "behind"
    assert progress["active_lesson"]["id"] == str(active.id)
    assert 21.5 < progress["active_lesson"]["hours_remaining_in_pace_window"] < 22.5
    assert profile["time_budget"] == {"minutes_per_session": 15}
    assert profile["schedule"]["pace_window_hours"] == 24


async def test_new_user_is_not_started(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    assert (await client.get("/api/v1/progress")).json()["pace_summary"] == "not_started"
    assert (await client.get("/api/v1/profile")).json()["schedule"]["pace_summary"] == "not_started"


async def test_progress_requires_onboarding(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, onboarding_complete=False)
    response = await client.get("/api/v1/progress")
    assert response.status_code == 403
    assert response.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_reports_are_empty_until_written(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    body = (await client.get("/api/v1/reports/progress")).json()
    assert body == {"report_type": "progress", "body": None, "updated_at": None}
