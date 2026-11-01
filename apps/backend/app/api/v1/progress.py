from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarding_complete
from app.db.session import get_db
from app.models.user import User
from app.schemas.progress import ActiveLessonOut, ProgressResponse
from app.services.pace import hours_remaining_in_pace_window, pace_snapshot, pace_window

router = APIRouter(tags=["progress"])


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    snapshot = await pace_snapshot(db, user.id)
    profile, active = snapshot.profile, snapshot.active_lesson
    return ProgressResponse(
        plan_days_done=snapshot.plan_days_done,
        target_plan_days=profile.target_plan_days if profile else None,
        plan_slip_days=profile.plan_slip_days if profile else 0,
        projected_completion_at=profile.projected_completion_at if profile else None,
        pace_summary=snapshot.summary,
        active_lesson=None
        if active is None
        else ActiveLessonOut(
            id=str(active.id),
            lesson_number=active.lesson_number,
            started_at=active.started_at,
            hours_remaining_in_pace_window=hours_remaining_in_pace_window(active.started_at, pace_window(profile)),
        ),
    )
