from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.enums import LessonStatus
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.schemas.profile import ProfileResponse, ProfileUpdateRequest, ScheduleOut
from app.services.pace import compute_profile_pace_summary

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    lessons = Lesson.user_id == user.id
    plan_days_done = await db.scalar(
        select(func.count()).select_from(Lesson).where(lessons, Lesson.status == LessonStatus.accomplished)
    )
    active = (
        await db.execute(
            select(Lesson).where(lessons, Lesson.status.in_([LessonStatus.generating, LessonStatus.active]))
        )
    ).scalar_one_or_none()
    last_done = (
        await db.execute(
            select(Lesson)
            .where(lessons, Lesson.status == LessonStatus.accomplished)
            .order_by(Lesson.accomplished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    focus = (profile.focus if profile else None) or {}
    return ProfileResponse(
        goal_summary=profile.goal_outcome if profile else None,
        level=profile.target_level if profile else None,
        native_language=profile.native_language if profile else None,
        target_language=profile.target_language if profile else None,
        time_budget=profile.time_budget if profile else None,
        topics=focus.get("topic_priorities") or [],
        vocab_priorities=focus.get("vocab_priorities") or [],
        grammar_mastery=(profile.grammar_mastery if profile else None) or {},
        schedule=ScheduleOut(
            target_plan_days=profile.target_plan_days if profile else None,
            plan_days_done=plan_days_done or 0,
            plan_slip_days=profile.plan_slip_days if profile else 0,
            projected_completion_at=profile.projected_completion_at if profile else None,
            pace_window_hours=profile.pace_window_hours if profile else 24,
            pace_summary=compute_profile_pace_summary(profile, active, last_done),
        ),
    )


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Set the lesson length (merged into `time_budget`). Profiles from before lesson timing
    have none, and `POST /lessons/start` answers 409 TIME_BUDGET_REQUIRED until it is set."""
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        raise APIError(404, "Profile not found", "NOT_FOUND")
    profile.time_budget = {**(profile.time_budget or {}), **body.time_budget.model_dump()}
    await db.commit()
    return await get_profile(user, db)
