"""`POST /api/v1/onboarding/accept` — persists the accepted course roadmap and
unlocks the app. Implements the exact sequence from
docs/tech_requirements/database.md "Onboarding data flow".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
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
from app.services.report_seed import seed_four_week_plan_markdown, seed_roadmap_markdown

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/accept", response_model=OnboardingAcceptResponse)
async def accept_onboarding(
    body: OnboardingAcceptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingAcceptResponse:
    try:
        session_uuid = uuid.UUID(body.session_id)
    except ValueError:
        raise APIError(404, "Onboarding chat session not found", "NOT_FOUND") from None

    session_result = await db.execute(select(ChatSession).where(ChatSession.id == session_uuid))
    session = session_result.scalar_one_or_none()
    if session is None or session.user_id != user.id or session.type != ChatSessionType.onboarding:
        raise APIError(404, "Onboarding chat session not found", "NOT_FOUND")

    goal_result = await db.execute(
        select(LearningGoal)
        .where(LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.draft)
        .order_by(LearningGoal.created_at.desc())
    )
    goal = goal_result.scalars().first()
    if goal is None:
        # The interview never persisted a learner_profile (structured
        # extraction never fired) — there is no goal to attach the plan to.
        raise APIError(
            422,
            "No draft learning goal found; complete the onboarding interview before accepting a plan",
            "ONBOARDING_INTERVIEW_INCOMPLETE",
        )

    now = datetime.now(timezone.utc)
    roadmap = body.course_roadmap

    plan = LearningPlan(
        user_id=user.id,
        learning_goal_id=goal.id,
        status=LearningPlanStatus.accepted,
        roadmap=roadmap.model_dump(),
        current_milestone_index=roadmap.current_milestone_index,
        accepted_at=now,
    )
    db.add(plan)
    await db.flush()  # assign plan.id before referencing it on `profiles`

    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user.id, pace_window_hours=settings.pace_window_hours)
        db.add(profile)
        await db.flush()

    pace_window_hours = profile.pace_window_hours or settings.pace_window_hours
    profile.active_learning_plan_id = plan.id
    profile.target_plan_days = roadmap.summary.target_plan_days
    # Initial projection ≈ accept time + target_plan_days × pace window, per
    # backend.md "Plan schedule and pacing" (display may round to calendar days).
    profile.projected_completion_at = now + timedelta(
        hours=roadmap.summary.target_plan_days * pace_window_hours
    )

    goal.status = LearningGoalStatus.active

    user.onboarding_complete = True
    user.plan_accepted_at = now

    db.add(
        UserReport(
            user_id=user.id,
            report_type=UserReportType.roadmap,
            body=seed_roadmap_markdown(roadmap),
        )
    )
    db.add(
        UserReport(
            user_id=user.id,
            report_type=UserReportType.four_week_plan,
            body=seed_four_week_plan_markdown(roadmap),
        )
    )

    # Retention (database.md): delete the onboarding chat transcript + session
    # on accept — `profiles` / `learning_plans` are the long-term store now.
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))

    await db.commit()

    return OnboardingAcceptResponse(onboarding_complete=True, plan_accepted_at=now)
