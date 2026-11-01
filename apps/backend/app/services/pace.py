"""Pace math shared by lesson finish, `GET /progress`, and `GET /profile`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.models.enums import PaceStatus
from app.models.lesson import Lesson
from app.models.profile import Profile


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
    window = (profile.pace_window_hours if profile else None) or 24
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
