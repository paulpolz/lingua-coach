"""Pace math shared by lesson finish, `GET /progress`, and `GET /profile`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import PaceStatus
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.services import queries


def pace_window(profile: Profile | None) -> int:
    return (profile.pace_window_hours if profile else None) or settings.pace_window_hours


def compute_lesson_pace_status(
    started_at: datetime | None, accomplished_at: datetime, pace_window_hours: int
) -> PaceStatus:
    if started_at is None:
        return PaceStatus.on_pace
    elapsed_hours = (accomplished_at - started_at).total_seconds() / 3600
    return PaceStatus.slipped if elapsed_hours > pace_window_hours else PaceStatus.on_pace


def compute_projected_completion(now: datetime, remaining_plan_days: int, pace_window_hours: int) -> datetime:
    return now + timedelta(hours=max(remaining_plan_days, 0) * pace_window_hours)


def hours_remaining_in_pace_window(started_at: datetime | None, pace_window_hours: int) -> float:
    """Negative when the active lesson is overdue."""
    if started_at is None:
        return float(pace_window_hours)
    return pace_window_hours - (datetime.now(UTC) - started_at).total_seconds() / 3600


PaceSummary = Literal["on_pace", "behind", "ahead", "not_started"]


def compute_profile_pace_summary(
    profile: Profile | None, active_lesson: Lesson | None, last_accomplished: Lesson | None
) -> PaceSummary:
    """behind: active lesson overdue or last finish slipped.
    ahead: last finish took at most half the window and the plan never slipped.
    on_pace otherwise; not_started before any lesson."""
    if active_lesson is None and last_accomplished is None:
        return "not_started"
    window = pace_window(profile)
    if active_lesson is not None and active_lesson.started_at is not None:
        if hours_remaining_in_pace_window(active_lesson.started_at, window) < 0:
            return "behind"
    if last_accomplished is not None:
        if last_accomplished.pace_status == PaceStatus.slipped:
            return "behind"
        start, end = last_accomplished.started_at, last_accomplished.accomplished_at
        slip_days = (profile.plan_slip_days if profile else 0) or 0
        if start and end and (end - start).total_seconds() / 3600 <= window / 2 and slip_days == 0:
            return "ahead"
    return "on_pace"


@dataclass(frozen=True)
class PaceSnapshot:
    profile: Profile | None
    plan_days_done: int
    active_lesson: Lesson | None
    last_accomplished: Lesson | None
    summary: PaceSummary


async def pace_snapshot(db: AsyncSession, user_id: uuid.UUID) -> PaceSnapshot:
    """What `GET /progress` and `GET /profile` both report about the schedule."""
    profile = await queries.get_profile(db, user_id)
    active = await queries.active_lesson(db, user_id)
    last = await queries.last_accomplished(db, user_id)
    return PaceSnapshot(
        profile=profile,
        plan_days_done=await queries.accomplished_count(db, user_id),
        active_lesson=active,
        last_accomplished=last,
        summary=compute_profile_pace_summary(profile, active, last),
    )
