"""Row factories. Each flushes so app sessions on the same connection see the row."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.enums import (
    ChatMessageRole,
    ChatSessionType,
    LearningGoalStatus,
    LearningPlanStatus,
    LessonStatus,
)
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.user import User


async def _save(db: AsyncSession, obj: Any) -> Any:
    db.add(obj)
    await db.flush()
    return obj


async def make_user(db: AsyncSession, *, clerk_user_id: str = "user_test", onboarding_complete: bool = True) -> User:
    return await _save(db, User(clerk_user_id=clerk_user_id, onboarding_complete=onboarding_complete))


async def make_profile(db: AsyncSession, user: User, *, minutes_per_session: int | None = 15, **fields: Any) -> Profile:
    defaults: dict[str, Any] = {
        "native_language": "ru",
        "target_language": "en",
        "goal_outcome": "Write work emails",
        "target_level": "B1",
        "pace_window_hours": 24,
        "target_plan_days": 30,
        "time_budget": {"minutes_per_session": minutes_per_session} if minutes_per_session else None,
    }
    return await _save(db, Profile(user_id=user.id, **{**defaults, **fields}))


def roadmap_dict(**overrides: Any) -> dict[str, Any]:
    roadmap: dict[str, Any] = {
        "version": 1,
        "summary": {
            "goal_outcome": "Travel",
            "goal_horizon": "3 months",
            "starting_level": "A2",
            "target_plan_days": 30,
        },
        "milestones": [{"index": 0, "title": "Basics"}],
    }
    return {**roadmap, **overrides}


async def make_goal(
    db: AsyncSession, user: User, *, status: LearningGoalStatus = LearningGoalStatus.draft
) -> LearningGoal:
    return await _save(db, LearningGoal(user_id=user.id, status=status, goal_statement="Travel"))


async def make_plan(db: AsyncSession, user: User, *, roadmap: dict[str, Any] | None = None) -> LearningPlan:
    goal = await make_goal(db, user, status=LearningGoalStatus.active)
    return await _save(
        db,
        LearningPlan(
            user_id=user.id,
            learning_goal_id=goal.id,
            status=LearningPlanStatus.accepted,
            roadmap=roadmap or roadmap_dict(),
            accepted_at=datetime.now(UTC),
        ),
    )


async def make_lesson(
    db: AsyncSession,
    user: User,
    *,
    status: LessonStatus = LessonStatus.active,
    lesson_number: int = 1,
    payload: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Lesson:
    lesson = Lesson(
        user_id=user.id,
        lesson_number=lesson_number,
        status=status,
        payload=payload if payload is not None else {"version": 1, "curriculum": {}, "session_summary": None},
        started_at=started_at or (datetime.now(UTC) if status == LessonStatus.active else None),
    )
    if created_at is not None:
        lesson.created_at = created_at
    return await _save(db, lesson)


async def make_chat_session(db: AsyncSession, user: User, lesson: Lesson | None = None) -> ChatSession:
    session_type = ChatSessionType.lesson if lesson else ChatSessionType.onboarding
    return await _save(db, ChatSession(user_id=user.id, type=session_type, lesson_id=lesson.id if lesson else None))


async def make_messages(
    db: AsyncSession, session: ChatSession, minutes: list[float], *, start: datetime | None = None
) -> list[ChatMessage]:
    """Alternating user/assistant messages at the given minute offsets from `start`."""
    base = start or datetime.now(UTC) - timedelta(minutes=max(minutes, default=0))
    rows = []
    for i, offset in enumerate(minutes):
        msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.user if i % 2 == 0 else ChatMessageRole.assistant,
            content=f"message {i}",
            metadata_json=None,
        )
        msg.created_at = base + timedelta(minutes=offset)
        rows.append(await _save(db, msg))
    return rows


async def make_mistake(db: AsyncSession, user: User, pattern_type: str, **fields: Any) -> Mistake:
    defaults: dict[str, Any] = {
        "example_text": f"example of {pattern_type}",
        "correction": "fixed",
        "occurrence_count": 1,
        "next_review_at": datetime.now(UTC) - timedelta(hours=1),
    }
    return await _save(db, Mistake(user_id=user.id, pattern_type=pattern_type, **{**defaults, **fields}))


def new_uuid() -> str:
    return str(uuid.uuid4())
