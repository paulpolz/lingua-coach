"""Shared plan-pacing logic — docs/tech_requirements/backend.md "Plan schedule
and pacing" + docs/tech_requirements/database.md "Plan schedule rules".

Used by `POST /lessons/{id}/finish`, `GET /progress`, and `GET /profile` so
all three surfaces agree on the same on-pace / slip / projection math.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.enums import PaceStatus
from app.models.lesson import Lesson
from app.models.profile import Profile


def compute_lesson_pace_status(
    started_at: datetime | None, accomplished_at: datetime, pace_window_hours: int
) -> PaceStatus:
    """backend.md: on-pace = finish within `pace_window_hours` of `started_at`;
    otherwise slipped. `started_at` should always be set for an `active`
    lesson (it is stamped when the generation job succeeds) — the `None`
    fallback below is defensive only and treats an unstarted clock as
    trivially on-pace rather than raising."""
    if started_at is None:
        return PaceStatus.on_pace
    elapsed_hours = (accomplished_at - started_at).total_seconds() / 3600
    return PaceStatus.slipped if elapsed_hours > pace_window_hours else PaceStatus.on_pace


def compute_projected_completion(
    now: datetime, remaining_plan_days: int, pace_window_hours: int
) -> datetime:
    """Mirrors the accept-time formula (onboarding.py): `now + remaining_days
    × pace_window_hours` hours, at the ideal one-lesson-per-window pace.
    Negative `remaining_plan_days` (target already met/exceeded) clamps to 0
    so the projection never moves into the past."""
    remaining = max(remaining_plan_days, 0)
    return now + timedelta(hours=remaining * pace_window_hours)


def hours_remaining_in_pace_window(
    started_at: datetime | None, pace_window_hours: int, *, now: datetime | None = None
) -> float:
    """`GET /progress`'s `active_lesson.hours_remaining_in_pace_window`.

    Deliberately **not clamped to 0** when overdue — a negative value is
    meaningful signal ("2.5h over the window") that the frontend can surface
    as a pace warning rather than silently flooring at "no time left".
    If the lesson hasn't started its pace clock yet (still `generating`,
    `started_at is None`), the full window remains.
    """
    if started_at is None:
        return float(pace_window_hours)
    now = now or datetime.now(timezone.utc)
    elapsed_hours = (now - started_at).total_seconds() / 3600
    return pace_window_hours - elapsed_hours


def compute_profile_pace_summary(
    profile: Profile | None,
    active_lesson: Lesson | None,
    most_recent_accomplished_lesson: Lesson | None,
) -> str:
    """Profile/dashboard-level `pace_summary` — `"not_started"` |
    `"on_pace"` | `"behind"` | `"ahead"`.

    docs/implementation-readiness.md §6 defines the enum but not the exact
    thresholds beyond the per-lesson `pace_status` (`on_pace`/`slipped`).
    Heuristic chosen for MVP (documented here since Phase 5 leaves this to
    the implementer's judgment):

    - **`not_started`**: no lesson has ever been started or accomplished —
      there is no pace signal yet.
    - **`behind`**: either (a) there is a currently active lesson that has
      already run *longer than* `pace_window_hours` without being finished
      (overdue right now), or (b) the most recently accomplished lesson
      slipped (`pace_status == "slipped"`) — i.e. the last completed signal
      was a miss and nothing since has shown recovery.
    - **`ahead`**: the most recently accomplished lesson finished in at most
      half of `pace_window_hours` (i.e. comfortably faster than the ideal
      one-lesson-per-window baseline) *and* the learner has zero cumulative
      slip (`plan_slip_days == 0`) — a simple "consistently faster than pace
      with a clean record" signal. Intentionally conservative/rare per the
      task brief ("ahead" is optional/rare for MVP).
    - **`on_pace`**: the default steady state — an active lesson still
      within its window, or the last finish was on pace without qualifying
      as "ahead".
    """
    if active_lesson is None and most_recent_accomplished_lesson is None:
        return "not_started"

    pace_window_hours = (profile.pace_window_hours if profile else None) or 24
    plan_slip_days = (profile.plan_slip_days if profile else None) or 0

    if active_lesson is not None and active_lesson.started_at is not None:
        if hours_remaining_in_pace_window(active_lesson.started_at, pace_window_hours) < 0:
            return "behind"

    if most_recent_accomplished_lesson is not None:
        if most_recent_accomplished_lesson.pace_status == PaceStatus.slipped:
            return "behind"

        started_at = most_recent_accomplished_lesson.started_at
        accomplished_at = most_recent_accomplished_lesson.accomplished_at
        if started_at is not None and accomplished_at is not None:
            duration_hours = (accomplished_at - started_at).total_seconds() / 3600
            if duration_hours <= pace_window_hours / 2 and plan_slip_days == 0:
                return "ahead"

    return "on_pace"
