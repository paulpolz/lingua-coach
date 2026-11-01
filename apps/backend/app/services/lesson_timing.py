"""Lesson time budget. The LLM cannot measure time, so the backend does.

Active minutes are the sum of gaps between consecutive lesson-chat messages, each gap
capped at `settings.lesson_idle_cap_minutes`, so a learner who leaves the tab for an hour
adds the cap, not 60 minutes. This is separate from `lessons.started_at`, which drives
the pace clock. The target is the learner's `time_budget.minutes_per_session`; there is
no default lesson length.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.models.lesson import Lesson
from app.models.profile import Profile


class TimeBudgetRequired(Exception):
    """The profile has no lesson length. Routers map this to TIME_BUDGET_REQUIRED."""


def active_minutes_between(times: Sequence[datetime], idle_cap_minutes: int) -> int:
    ordered = sorted(times)
    cap_seconds = idle_cap_minutes * 60
    gaps = (later - earlier for earlier, later in zip(ordered, ordered[1:], strict=False))
    seconds = sum(min(gap.total_seconds(), cap_seconds) for gap in gaps)
    return int(seconds // 60)


async def active_minutes(
    db: AsyncSession, session_id: uuid.UUID, idle_cap_minutes: int, *, until: datetime | None = None
) -> int:
    """Active minutes in a lesson chat. `until` (now) closes the gap after the last message."""
    times = list(
        (await db.execute(select(ChatMessage.created_at).where(ChatMessage.session_id == session_id))).scalars()
    )
    if until is not None and times:
        times.append(until)
    return active_minutes_between(times, idle_cap_minutes)


def target_minutes(profile: Profile | None) -> int:
    minutes = ((profile.time_budget if profile else None) or {}).get("minutes_per_session")
    if not isinstance(minutes, int) or minutes <= 0:
        raise TimeBudgetRequired
    return minutes


def lesson_target_minutes(lesson: Lesson, profile: Profile | None) -> int | None:
    """`payload.target_minutes` is fixed at generation, so a mid-lesson plan change does not
    move the goal. Lessons generated before timing existed fall back to the profile."""
    stored = (lesson.payload or {}).get("target_minutes")
    if isinstance(stored, int) and stored > 0:
        return stored
    try:
        return target_minutes(profile)
    except TimeBudgetRequired:
        return None
