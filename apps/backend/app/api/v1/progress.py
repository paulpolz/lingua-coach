"""`GET /api/v1/progress` — docs/implementation-readiness.md §6.

Not lesson-scoped (mirrors `jobs.py` living alongside `lessons.py`) — kept as
its own module since it aggregates lesson + profile state rather than acting
on a single lesson.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarding_complete
from app.db.session import get_db
from app.models.enums import LessonStatus
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.schemas.progress import ActiveLessonOut, ProgressResponse
from app.services.pace import compute_profile_pace_summary, hours_remaining_in_pace_window

router = APIRouter(tags=["progress"])

_ACTIVE_LESSON_STATUSES = (LessonStatus.generating, LessonStatus.active)


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()

    plan_days_done = (
        await db.scalar(
            select(func.count())
            .select_from(Lesson)
            .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
        )
        or 0
    )

    active_lesson_result = await db.execute(
        select(Lesson).where(Lesson.user_id == user.id, Lesson.status.in_(_ACTIVE_LESSON_STATUSES))
    )
    active_lesson = active_lesson_result.scalar_one_or_none()

    most_recent_accomplished_result = await db.execute(
        select(Lesson)
        .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
        .order_by(Lesson.accomplished_at.desc())
        .limit(1)
    )
    most_recent_accomplished_lesson = most_recent_accomplished_result.scalar_one_or_none()

    pace_window_hours = (profile.pace_window_hours if profile else None) or 24
    pace_summary = compute_profile_pace_summary(profile, active_lesson, most_recent_accomplished_lesson)

    active_lesson_out = None
    if active_lesson is not None:
        active_lesson_out = ActiveLessonOut(
            id=str(active_lesson.id),
            lesson_number=active_lesson.lesson_number,
            started_at=active_lesson.started_at,
            hours_remaining_in_pace_window=hours_remaining_in_pace_window(
                active_lesson.started_at, pace_window_hours
            ),
        )

    return ProgressResponse(
        plan_days_done=plan_days_done,
        target_plan_days=profile.target_plan_days if profile else None,
        plan_slip_days=profile.plan_slip_days if profile else 0,
        projected_completion_at=profile.projected_completion_at if profile else None,
        pace_summary=pace_summary,
        active_lesson=active_lesson_out,
    )
