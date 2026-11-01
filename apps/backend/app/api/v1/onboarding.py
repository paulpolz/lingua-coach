"""`POST /onboarding/accept`: the accepted roadmap becomes the plan and the app unlocks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatSessionType, LearningGoalStatus, LearningPlanStatus, UserReportType
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
from app.schemas.onboarding import OnboardingAcceptRequest, OnboardingAcceptResponse
from app.services.lesson_timing import TimeBudgetRequired, target_minutes
from app.services.report_seed import seed_four_week_plan_markdown, seed_roadmap_markdown

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/accept", response_model=OnboardingAcceptResponse)
async def accept_onboarding(
    body: OnboardingAcceptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingAcceptResponse:
    try:
        session = await db.get(ChatSession, uuid.UUID(body.session_id))
    except ValueError:
        session = None
    if session is None or session.user_id != user.id or session.type != ChatSessionType.onboarding:
        raise APIError(404, "Onboarding chat session not found", "NOT_FOUND")

    goal = (
        (
            await db.execute(
                select(LearningGoal)
                .where(LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.draft)
                .order_by(LearningGoal.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if goal is None:
        raise APIError(
            422,
            "No draft learning goal found; complete the onboarding interview before accepting a plan",
            "ONBOARDING_INTERVIEW_INCOMPLETE",
        )

    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    try:
        target_minutes(profile)
    except TimeBudgetRequired:
        raise APIError(
            422,
            "The plan needs a lesson length: tell the coach how many minutes each lesson should last.",
            "TIME_BUDGET_REQUIRED",
        ) from None
    assert profile is not None  # target_minutes() raises for a missing profile

    now = datetime.now(UTC)
    roadmap = body.course_roadmap.model_dump()
    plan_days = body.course_roadmap.summary.target_plan_days

    plan = LearningPlan(
        user_id=user.id,
        learning_goal_id=goal.id,
        status=LearningPlanStatus.accepted,
        roadmap=roadmap,
        current_milestone_index=body.course_roadmap.current_milestone_index or 0,
        accepted_at=now,
    )
    db.add(plan)
    await db.flush()

    profile.active_learning_plan_id = plan.id
    profile.target_plan_days = plan_days or None
    profile.projected_completion_at = now + timedelta(hours=plan_days * (profile.pace_window_hours or 24))

    goal.status = LearningGoalStatus.active
    user.onboarding_complete = True
    user.plan_accepted_at = now
    db.add_all(
        [
            UserReport(user_id=user.id, report_type=UserReportType.roadmap, body=seed_roadmap_markdown(roadmap)),
            UserReport(
                user_id=user.id,
                report_type=UserReportType.four_week_plan,
                body=seed_four_week_plan_markdown(roadmap),
            ),
        ]
    )

    # The transcript is disposable once the plan is accepted.
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.commit()
    return OnboardingAcceptResponse(onboarding_complete=True, plan_accepted_at=now)
