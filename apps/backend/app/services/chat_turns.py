"""Save one coach turn: profile, mistakes, practice, plan updates, and the transcript rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatMessageRole, LearningGoalStatus
from app.models.learning_goal import LearningGoal
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from app.schemas.chat import TurnMetadata, TurnTiming
from app.schemas.llm import (
    LearnerGoal,
    LearnerLevel,
    LearnerProfile,
    LessonReply,
    MistakeEntry,
    OnboardingReply,
    PracticeResult,
    normalize_pattern,
)
from app.services.lesson_timing import active_minutes, lesson_target_minutes
from app.services.pace import compute_projected_completion, pace_window
from app.services.queries import accomplished_count, get_profile

logger = get_logger(__name__)

# Days until the next review, keyed by occurrence count (exercise_tutor.md: +1, +3, +7, +14).
_REVIEW_DAYS = {1: 1, 2: 3, 3: 7}


async def _save_learner_profile(db: AsyncSession, user: User, data: LearnerProfile) -> None:
    """Upsert `profiles` and the draft `learning_goals` row from `learner_profile`."""
    goal = data.goal or LearnerGoal()
    level = data.level or LearnerLevel()

    profile = await get_profile(db, user.id)
    if profile is None:
        profile = Profile(user_id=user.id, pace_window_hours=settings.pace_window_hours)
        db.add(profile)
    profile.goal_outcome = goal.outcome
    profile.goal_horizon = goal.horizon
    profile.goal_success_criteria = goal.success_criteria
    profile.native_language = data.languages.native
    profile.target_language = data.languages.target
    profile.target_level = level.self_assessed
    profile.level_strengths = level.strengths
    profile.level_weaknesses = level.weaknesses
    profile.diagnostic_notes = level.diagnostic_notes
    profile.time_budget = data.time_budget.model_dump() if data.time_budget else None
    profile.focus = data.focus.model_dump() if data.focus else None
    profile.constraints = data.constraints.model_dump() if data.constraints else None
    profile.motivation = data.motivation.model_dump() if data.motivation else None
    profile.interview_completed_at = datetime.now(UTC)

    draft = (
        await db.execute(
            select(LearningGoal).where(LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.draft)
        )
    ).scalar_one_or_none()
    if draft is None:
        draft = LearningGoal(user_id=user.id, status=LearningGoalStatus.draft)
        db.add(draft)
    draft.goal_statement = goal.outcome
    draft.horizon = goal.horizon
    draft.success_criteria = goal.success_criteria


async def _upsert_mistakes(db: AsyncSession, user: User, lesson: Lesson, items: list[MistakeEntry]) -> None:
    """One row per (user, pattern_type): a repeat bumps the count and reschedules review.

    Patterns are deduped within the reply (first entry wins) and written with
    INSERT ... ON CONFLICT, so a repeated pattern can never create a second row.
    """
    now = datetime.now(UTC)
    unique: dict[str, MistakeEntry] = {}
    for item in items:
        unique.setdefault(item.pattern_type, item)  # already normalize_pattern()-ed by the schema
    for pattern, item in unique.items():
        stmt = insert(Mistake).values(
            user_id=user.id,
            pattern_type=pattern,
            example_text=item.example_text,
            correction=item.correction or None,
            lesson_id=lesson.id,
            occurrence_count=1,
            last_seen_at=now,
            next_review_at=now + timedelta(days=_REVIEW_DAYS[1]),
            solid_streak=0,
            last_solid_lesson_id=None,
        )
        count = Mistake.occurrence_count + 1
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_mistakes_user_id_pattern_type",
                set_={
                    "occurrence_count": count,
                    "example_text": func.coalesce(func.nullif(stmt.excluded.example_text, ""), Mistake.example_text),
                    "correction": func.coalesce(stmt.excluded.correction, Mistake.correction),
                    "lesson_id": stmt.excluded.lesson_id,
                    "last_seen_at": stmt.excluded.last_seen_at,
                    "next_review_at": stmt.excluded.last_seen_at
                    + func.make_interval(0, 0, 0, case(_REVIEW_DAYS, value=count, else_=14)),
                    # A repeat reopens a closed pattern and restarts its solid streak.
                    "solid_streak": 0,
                    "last_solid_lesson_id": None,
                    "resolved_at": None,
                    "updated_at": func.now(),
                },
            )
        )


def _review_days(occurrence_count: int) -> int:
    return _REVIEW_DAYS.get(occurrence_count, 14)


async def _apply_practiced(db: AsyncSession, user: User, lesson: Lesson, results: list[PracticeResult]) -> None:
    """Close the feedback loop on practiced items.

    On an open mistake pattern, `solid` pushes the review out one step and counts toward
    closing it, at most once per lesson: solid results in two different lessons close the
    pattern (spaced repetition, not two turns a minute apart). `shaky` restarts the streak.
    A `solid` grammar point is merged into `profiles.grammar_mastery`. Runs before the
    mistake upsert, so a mistake reported in the same reply wins.
    """
    latest = {(r.aspect, r.item.strip()): r for r in results if r.item.strip()}
    if not latest:
        return
    names = {normalize_pattern(item) for _, item in latest}
    open_mistakes = (
        await db.execute(
            select(Mistake).where(
                Mistake.user_id == user.id,
                Mistake.resolved_at.is_(None),
                func.lower(Mistake.pattern_type).in_(names),
            )
        )
    ).scalars()
    by_pattern = {normalize_pattern(m.pattern_type): m for m in open_mistakes}
    now = datetime.now(UTC)
    mastered: dict[str, str] = {}
    touched: set[str] = set()
    for (aspect, item), result in latest.items():
        # One streak step per pattern per reply, even if it is reported under two aspects.
        key = normalize_pattern(item)
        mistake = None if key in touched else by_pattern.get(key)
        touched.add(key)
        if mistake is not None and result.result == "solid":
            if mistake.last_solid_lesson_id != lesson.id:
                mistake.solid_streak += 1
                mistake.last_solid_lesson_id = lesson.id
            if mistake.solid_streak >= 2:
                mistake.resolved_at, mistake.next_review_at = now, None
            else:
                mistake.next_review_at = now + timedelta(days=_review_days(mistake.occurrence_count + 1))
        elif mistake is not None:
            mistake.solid_streak, mistake.last_solid_lesson_id = 0, None
        if aspect == "grammar" and result.result == "solid":
            mastered[item] = "solid"
    if mastered:
        profile = await get_profile(db, user.id)
        if profile is not None:
            profile.grammar_mastery = {**(profile.grammar_mastery or {}), **mastered}
    await db.flush()


async def _apply_plan_updates(db: AsyncSession, user: User, updates: dict) -> None:
    """Chat is the only plan editor: patch `profiles` and log a `plan_updated` event."""
    profile = await get_profile(db, user.id)
    if profile is None or not updates:
        return
    focus = dict(profile.focus or {})
    for key, column in (("goal_summary", "goal_outcome"), ("level", "target_level")):
        if updates.get(key) is not None:
            setattr(profile, column, updates[key])
    if isinstance(updates.get("time_budget"), dict):
        # Merge, so a change to one field never clears the lesson length.
        changed = {k: v for k, v in updates["time_budget"].items() if v is not None}
        profile.time_budget = {**(profile.time_budget or {}), **changed}
    if updates.get("topics") is not None:
        focus["topic_priorities"] = updates["topics"]
    if updates.get("vocab_priorities") is not None:
        focus["vocab_priorities"] = updates["vocab_priorities"]
    profile.focus = focus
    if isinstance(updates.get("grammar_mastery"), dict):
        profile.grammar_mastery = {**(profile.grammar_mastery or {}), **updates["grammar_mastery"]}
    target_days = updates.get("target_plan_days")
    if isinstance(target_days, int) and target_days != profile.target_plan_days:
        profile.target_plan_days = target_days
        remaining = target_days - await accomplished_count(db, user.id)
        profile.projected_completion_at = compute_projected_completion(
            datetime.now(UTC), remaining, pace_window(profile)
        )
    db.add(ProgressEvent(user_id=user.id, event_type="plan_updated", payload=updates))


async def _lesson_timing(
    db: AsyncSession, session: ChatSession, lesson: Lesson, profile: Profile | None
) -> TurnTiming | None:
    target = lesson_target_minutes(lesson, profile)
    if target is None:
        return None
    active = await active_minutes(db, session.id, settings.lesson_idle_cap_minutes, until=datetime.now(UTC))
    return TurnTiming(active_minutes=active, target_minutes=target)


async def _persist_turn(
    db: AsyncSession,
    user: User,
    lesson: Lesson | None,
    reply: OnboardingReply | LessonReply,
    timing: TurnTiming | None,
) -> TurnMetadata:
    """Upsert artifacts from the structured reply and return the turn metadata."""
    if isinstance(reply, OnboardingReply):
        profile = reply.learner_profile
        if profile is None:
            return TurnMetadata(course_roadmap_draft=reply.course_roadmap)
        await _save_learner_profile(db, user, profile)
        return TurnMetadata(
            plan_updates={
                "goal_summary": profile.goal.outcome if profile.goal else None,
                "level": profile.level.self_assessed if profile.level else None,
            },
            course_roadmap_draft=reply.course_roadmap,
        )

    if lesson is None:
        raise RuntimeError("lesson reply requires a lesson")

    await _apply_practiced(db, user, lesson, reply.practiced)
    await _upsert_mistakes(db, user, lesson, reply.mistakes)
    plan_updates = None if reply.plan_updates is None else reply.plan_updates.model_dump()
    if plan_updates is not None:
        await _apply_plan_updates(db, user, plan_updates)
    # The model cannot see a clock; hold back the wrap-up until the budget is nearly used.
    suggest_finish = reply.suggest_finish and (timing is None or timing.active_minutes >= timing.target_minutes - 1)
    return TurnMetadata(
        corrections=reply.corrections,
        tips=reply.tips,
        plan_updates=plan_updates,
        suggest_finish=suggest_finish,
        practiced=reply.practiced,
        timing=timing,
    )


async def save_user_message(db: AsyncSession, session: ChatSession, content: str) -> None:
    db.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content=content))
    await db.commit()


async def save_assistant(
    db: AsyncSession,
    user: User,
    session: ChatSession,
    lesson: Lesson | None,
    profile: Profile | None,
    reply: OnboardingReply | LessonReply,
) -> tuple[ChatMessage, TurnMetadata]:
    try:
        # Re-measure after the reply: the user row is saved and the call took time. This is the
        # value the UI shows and the suggest_finish guard uses.
        timing = await _lesson_timing(db, session, lesson, profile) if lesson is not None else None
        metadata = await _persist_turn(db, user, lesson, reply, timing)
        message = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.assistant,
            content=reply.content,
            metadata_json=metadata.model_dump(mode="json"),
        )
        db.add(message)
        await db.commit()
    except SQLAlchemyError:
        logger.warning(
            "chat_persist_failed",
            exc_info=True,
            extra={"event": "db_persist_failed", "user_id": str(user.id), "session_id": str(session.id)},
        )
        await db.rollback()
        raise APIError(500, "Could not save this turn. Please try again.", "PERSIST_FAILED") from None
    return message, metadata
