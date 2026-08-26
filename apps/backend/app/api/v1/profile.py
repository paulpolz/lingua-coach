"""`GET /api/v1/profile` — docs/implementation-readiness.md §6."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import LessonStatus
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.schemas.profile import ProfileResponse, ScheduleOut, TimeBudgetOut
from app.services.pace import compute_profile_pace_summary

router = APIRouter(prefix="/profile", tags=["profile"])

# skills/onboarding_interviewer.md's example intensity values ("sustainable")
# don't match readiness §8's enum (light|moderate|intensive) verbatim — map
# the model's free text onto the closest documented enum value.
_INTENSITY_MAP = {
    "light": "light",
    "easy": "light",
    "relaxed": "light",
    "moderate": "moderate",
    "sustainable": "moderate",
    "balanced": "moderate",
    "intensive": "intensive",
    "intense": "intensive",
    "aggressive": "intensive",
}


def _normalize_intensity(raw: str | None) -> str:
    if not raw:
        return "moderate"
    return _INTENSITY_MAP.get(raw.strip().lower(), "moderate")


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
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
        select(Lesson).where(
            Lesson.user_id == user.id,
            Lesson.status.in_([LessonStatus.generating, LessonStatus.active]),
        )
    )
    active_lesson = active_lesson_result.scalar_one_or_none()

    most_recent_accomplished_result = await db.execute(
        select(Lesson)
        .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
        .order_by(Lesson.accomplished_at.desc())
        .limit(1)
    )
    most_recent_accomplished_lesson = most_recent_accomplished_result.scalar_one_or_none()

    # Shared with `GET /progress` — see app/services/pace.py for the
    # documented on_pace/behind/ahead/not_started heuristic.
    pace_summary = compute_profile_pace_summary(profile, active_lesson, most_recent_accomplished_lesson)

    if profile is None:
        return ProfileResponse(
            goal_summary=None,
            level=None,
            native_language=None,
            target_language=None,
            time_budget=None,
            topics=[],
            vocab_priorities=[],
            grammar_mastery={},
            schedule=ScheduleOut(
                target_plan_days=None,
                plan_days_done=plan_days_done,
                plan_slip_days=0,
                projected_completion_at=None,
                pace_window_hours=24,
                pace_summary=pace_summary,
            ),
        )

    focus = profile.focus or {}
    time_budget_data = profile.time_budget or {}
    time_budget = (
        TimeBudgetOut(
            minutes_per_session=time_budget_data.get("minutes_per_session", 0),
            sessions_per_week=time_budget_data.get("sessions_per_week", 0),
            intensity=_normalize_intensity(time_budget_data.get("intensity")),
        )
        if time_budget_data
        else None
    )

    return ProfileResponse(
        goal_summary=profile.goal_outcome,
        level=profile.target_level,
        native_language=profile.native_language,
        target_language=profile.target_language,
        time_budget=time_budget,
        topics=focus.get("topic_priorities", []),
        vocab_priorities=focus.get("vocab_priorities", []),
        grammar_mastery=profile.grammar_mastery or {},
        schedule=ScheduleOut(
            target_plan_days=profile.target_plan_days,
            plan_days_done=plan_days_done,
            plan_slip_days=profile.plan_slip_days,
            projected_completion_at=profile.projected_completion_at,
            pace_window_hours=profile.pace_window_hours,
            pace_summary=pace_summary,
        ),
    )
