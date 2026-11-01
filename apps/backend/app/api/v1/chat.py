"""Chat sessions and coach turns for onboarding and lessons."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import get_current_user
from app.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatMessageRole, ChatSessionType, LearningGoalStatus, LessonStatus
from app.models.learning_goal import LearningGoal
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.progress_event import ProgressEvent
from app.models.user import User
from app.schemas.chat import (
    ChatMessageCreateRequest,
    ChatMessageOut,
    ChatMessagesListResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatTurnResponse,
)
from app.schemas.llm import LessonReply, OnboardingReply
from app.services.gemini import ChatTurn, GeminiError
from app.services.llm_usage import check_and_record_user_limit, metered_structured_call
from app.services.prompt_assembly import (
    lesson_context_block,
    lesson_system_instruction,
    onboarding_system_instruction,
)
from app.services.skills import should_include_vocab_formats

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Days until the next review, keyed by occurrence count (exercise_tutor.md: +1, +3, +7, +14).
_REVIEW_DAYS = {1: 1, 2: 3, 3: 7}

_GEMINI_STATUS = {
    "LLM_TIMEOUT": 504,
    "LLM_QUOTA_EXCEEDED": 429,
    "LLM_SCHEMA_ERROR": 502,
    "LLM_API_ERROR": 502,
    "LLM_CONFIG_ERROR": 502,
}


def _uuid_or_404(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise APIError(404, f"{what} not found", "NOT_FOUND") from None


async def _owned_session(db: AsyncSession, session_id: str, user: User) -> ChatSession:
    session = await db.get(ChatSession, _uuid_or_404(session_id, "Chat session"))
    if session is None or session.user_id != user.id:
        raise APIError(404, "Chat session not found", "NOT_FOUND")
    return session


async def _owned_lesson(db: AsyncSession, lesson_id: uuid.UUID | None, user: User) -> Lesson:
    lesson = await db.get(Lesson, lesson_id) if lesson_id else None
    if lesson is None or lesson.user_id != user.id:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    return lesson


async def _profile(db: AsyncSession, user: User) -> Profile | None:
    return (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()


async def _get_or_create_session(db: AsyncSession, user: User, lesson: Lesson | None) -> ChatSession:
    """One onboarding session per user and one session per lesson, via partial unique indexes.

    `index_where` must repeat the index predicate as literal SQL; a bound enum does not match.
    """
    if lesson is None:
        stmt = (
            insert(ChatSession)
            .values(user_id=user.id, type=ChatSessionType.onboarding, lesson_id=None)
            .on_conflict_do_nothing(index_elements=["user_id"], index_where=text("type = 'onboarding'"))
        )
        where: tuple[ColumnElement[bool], ...] = (ChatSession.type == ChatSessionType.onboarding,)
    else:
        stmt = (
            insert(ChatSession)
            .values(user_id=user.id, type=ChatSessionType.lesson, lesson_id=lesson.id)
            .on_conflict_do_nothing(
                index_elements=["user_id", "lesson_id"],
                index_where=text("type = 'lesson' AND lesson_id IS NOT NULL"),
            )
        )
        where = (ChatSession.type == ChatSessionType.lesson, ChatSession.lesson_id == lesson.id)

    await db.execute(stmt)
    await db.commit()
    return (await db.execute(select(ChatSession).where(ChatSession.user_id == user.id, *where))).scalar_one()


@router.post("/sessions", status_code=201, response_model=ChatSessionResponse)
async def create_chat_session(
    body: ChatSessionCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    if body.type == "onboarding":
        session = await _get_or_create_session(db, user, None)
        return ChatSessionResponse(id=str(session.id), type="onboarding")

    if not body.lesson_id:
        raise APIError(422, "lesson_id is required for type=lesson", "LESSON_ID_REQUIRED")
    if not user.onboarding_complete:
        raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
    lesson = await _owned_lesson(db, _uuid_or_404(body.lesson_id, "Lesson"), user)
    if lesson.status not in (LessonStatus.generating, LessonStatus.active):
        raise APIError(409, f"Lesson is {lesson.status.value}", "LESSON_NOT_ACTIVE")
    session = await _get_or_create_session(db, user, lesson)
    return ChatSessionResponse(id=str(session.id), type="lesson", lesson_id=str(lesson.id))


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesListResponse)
async def list_chat_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessagesListResponse:
    session = await _owned_session(db, session_id, user)
    rows = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
        )
    ).scalars()
    return ChatMessagesListResponse(
        messages=[
            ChatMessageOut(
                id=str(m.id), role=m.role.value, content=m.content, created_at=m.created_at, metadata=m.metadata_json
            )
            for m in rows
        ]
    )


async def _save_learner_profile(db: AsyncSession, user: User, data: dict) -> None:
    """Upsert `profiles` and the draft `learning_goals` row from `learner_profile`."""
    goal = data.get("goal") or {}
    level = data.get("level") or {}
    languages = data.get("languages") or {}

    profile = await _profile(db, user)
    if profile is None:
        profile = Profile(user_id=user.id, pace_window_hours=settings.pace_window_hours)
        db.add(profile)
    profile.goal_outcome = goal.get("outcome")
    profile.goal_horizon = goal.get("horizon")
    profile.goal_success_criteria = goal.get("success_criteria")
    profile.native_language = (languages.get("native") or "").strip() or None
    profile.target_language = (languages.get("target") or "").strip() or None
    profile.target_level = level.get("self_assessed")
    profile.level_strengths = level.get("strengths")
    profile.level_weaknesses = level.get("weaknesses")
    profile.diagnostic_notes = level.get("diagnostic_notes")
    profile.time_budget = data.get("time_budget")
    profile.focus = data.get("focus")
    profile.constraints = data.get("constraints")
    profile.motivation = data.get("motivation")
    profile.interview_completed_at = datetime.now(UTC)

    draft = (
        await db.execute(
            select(LearningGoal).where(LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.draft)
        )
    ).scalar_one_or_none()
    if draft is None:
        draft = LearningGoal(user_id=user.id, status=LearningGoalStatus.draft)
        db.add(draft)
    draft.goal_statement = goal.get("outcome")
    draft.horizon = goal.get("horizon")
    draft.success_criteria = goal.get("success_criteria")


async def _upsert_mistake(db: AsyncSession, user: User, lesson: Lesson, item: dict) -> None:
    """Same user + pattern_type bumps the count and reschedules review; otherwise insert."""
    pattern = str(item.get("pattern_type") or "")[:255]
    if not pattern:
        return
    now = datetime.now(UTC)
    mistake = (
        await db.execute(select(Mistake).where(Mistake.user_id == user.id, Mistake.pattern_type == pattern))
    ).scalar_one_or_none()
    if mistake is None:
        mistake = Mistake(user_id=user.id, pattern_type=pattern, occurrence_count=0)
        db.add(mistake)
    mistake.occurrence_count += 1
    mistake.example_text = item.get("example_text") or mistake.example_text or ""
    mistake.correction = item.get("correction") or mistake.correction
    mistake.lesson_id = lesson.id
    mistake.last_seen_at = now
    mistake.next_review_at = now + timedelta(days=_REVIEW_DAYS.get(mistake.occurrence_count, 14))


async def _apply_plan_updates(db: AsyncSession, user: User, updates: dict) -> None:
    """Chat is the only plan editor: patch `profiles` and log a `plan_updated` event."""
    profile = await _profile(db, user)
    if profile is None or not updates:
        return
    focus = dict(profile.focus or {})
    for key, column in (("goal_summary", "goal_outcome"), ("level", "target_level"), ("time_budget", "time_budget")):
        if updates.get(key) is not None:
            setattr(profile, column, updates[key])
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
        done = await db.scalar(
            select(func.count())
            .select_from(Lesson)
            .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
        )
        profile.projected_completion_at = datetime.now(UTC) + timedelta(
            hours=max(target_days - (done or 0), 0) * profile.pace_window_hours
        )
    db.add(ProgressEvent(user_id=user.id, event_type="plan_updated", payload=updates))


async def _build_prompt(
    db: AsyncSession, user: User, lesson: Lesson | None, history: list[ChatTurn]
) -> tuple[str, list[ChatTurn]]:
    profile = await _profile(db, user)
    native = profile.native_language if profile else None
    target = profile.target_language if profile else None
    if lesson is None:
        return onboarding_system_instruction(native, target), history

    curriculum = (lesson.payload or {}).get("curriculum") or {}
    due = (
        (
            await db.execute(
                select(Mistake)
                .where(Mistake.user_id == user.id, Mistake.next_review_at <= datetime.now(UTC))
                .order_by(Mistake.next_review_at)
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    system = lesson_system_instruction(native, target, should_include_vocab_formats(curriculum))
    return system, [ChatTurn(role="user", text=lesson_context_block(curriculum, profile, due)), *history]


async def _persist_turn(
    db: AsyncSession,
    user: User,
    lesson: Lesson | None,
    reply: OnboardingReply | LessonReply,
) -> dict:
    """Upsert artifacts from the structured reply and return the seven metadata keys."""
    if isinstance(reply, OnboardingReply):
        profile = reply.learner_profile
        if profile is not None:
            await _save_learner_profile(db, user, profile.model_dump())
        goal = profile.goal if profile is not None else None
        level = profile.level if profile is not None else None
        return {
            "corrections": [],
            "tips": [],
            "plan_updates": {
                "goal_summary": None if goal is None else goal.outcome,
                "level": None if level is None else level.self_assessed,
            }
            if profile is not None
            else None,
            "suggest_finish": False,
            "course_roadmap_draft": None if reply.course_roadmap is None else reply.course_roadmap.model_dump(),
            "lesson_plan": None,
            "task_update": None,
        }

    if lesson is None or not isinstance(reply, LessonReply):
        raise RuntimeError("lesson reply requires a lesson")

    for item in reply.mistakes:
        await _upsert_mistake(db, user, lesson, item.model_dump())
    plan_updates = None if reply.plan_updates is None else reply.plan_updates.model_dump()
    if plan_updates is not None:
        await _apply_plan_updates(db, user, plan_updates)
    task_ids = list(reply.completed_task_ids)
    return {
        "corrections": [item.model_dump() for item in reply.corrections],
        "tips": list(reply.tips),
        "plan_updates": plan_updates,
        "suggest_finish": reply.suggest_finish,
        "course_roadmap_draft": None,
        "lesson_plan": None if reply.lesson_plan is None else reply.lesson_plan.model_dump(),
        "task_update": {"completed_task_ids": task_ids} if task_ids else None,
    }


@router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
async def post_chat_message(
    session_id: str,
    body: ChatMessageCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatTurnResponse:
    session = await _owned_session(db, session_id, user)
    content = body.content.strip()
    if not content:
        raise APIError(422, "Message content must not be empty", "EMPTY_MESSAGE")
    if len(content) > settings.max_message_chars:
        raise APIError(422, f"Message exceeds {settings.max_message_chars} characters", "MESSAGE_TOO_LONG")
    await check_and_record_user_limit(db, user.id, kind="chat")

    lesson = None
    if session.type == ChatSessionType.lesson:
        if not user.onboarding_complete:
            raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
        lesson = await _owned_lesson(db, session.lesson_id, user)

    recent = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(max(settings.chat_context_messages - 1, 0))
            )
        )
        .scalars()
        .all()
    )
    history = [
        ChatTurn(role="model" if m.role == ChatMessageRole.assistant else "user", text=m.content)
        for m in reversed(recent)
    ] + [ChatTurn(role="user", text=content)]
    system_instruction, contents = await _build_prompt(db, user, lesson, history)

    async def save_user_message() -> None:
        db.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content=content))
        await db.commit()

    schema: type[OnboardingReply] | type[LessonReply] = OnboardingReply if lesson is None else LessonReply
    try:
        reply = await metered_structured_call(
            db,
            user.id,
            "chat",
            model_id=settings.gemini_model_chat,
            schema=schema,
            system_instruction=system_instruction,
            history=contents,
            before_call=save_user_message,
        )
    except GeminiError as exc:
        raise APIError(_GEMINI_STATUS.get(exc.code, 502), str(exc), exc.code) from exc

    try:
        metadata = await _persist_turn(db, user, lesson, reply)
        message = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.assistant,
            content=reply.content,
            metadata_json=metadata,
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
    return ChatTurnResponse(message_id=str(message.id), content=message.content, metadata=metadata)
