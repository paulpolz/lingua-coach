"""Chat sessions and coach turns for onboarding and lessons."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import get_current_user, get_owned
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
    TurnMetadata,
    TurnTiming,
)
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
from app.services.agents.lesson_chat import lesson_agent
from app.services.agents.onboarding import onboarding_agent
from app.services.agents.runner import LLMError, StreamItem, metered_agent_run, metered_agent_stream, public_detail
from app.services.agents.tools import AgentContext
from app.services.lesson_timing import active_minutes, lesson_target_minutes
from app.services.llm_usage import check_and_record_user_limit
from app.services.pace import compute_projected_completion, pace_window
from app.services.queries import accomplished_count, get_profile

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Days until the next review, keyed by occurrence count (exercise_tutor.md: +1, +3, +7, +14).
_REVIEW_DAYS = {1: 1, 2: 3, 3: 7}

_LLM_STATUS = {
    "LLM_TIMEOUT": 504,
    "LLM_QUOTA_EXCEEDED": 429,
    "LLM_SCHEMA_ERROR": 502,
    "LLM_API_ERROR": 502,
    "LLM_CONFIG_ERROR": 502,
}


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
    lesson = await get_owned(db, Lesson, body.lesson_id, user, "Lesson")
    if lesson.status not in (LessonStatus.generating, LessonStatus.active):
        raise APIError(409, f"Lesson is {lesson.status.value}", "LESSON_NOT_ACTIVE")
    session = await _get_or_create_session(db, user, lesson)
    return ChatSessionResponse(id=str(session.id), type="lesson", lesson_id=str(lesson.id))


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesListResponse)
async def list_chat_messages(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessagesListResponse:
    session = await get_owned(db, ChatSession, session_id, user, "Chat session")
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


def _checkpointer(request: Request):
    saver = getattr(request.app.state, "checkpointer", None)
    if saver is None:
        raise APIError(503, "The coach is unavailable right now. Please try again.", "CHECKPOINTER_UNAVAILABLE")
    return saver


async def _prepare_turn(
    db: AsyncSession, user: User, session_id: uuid.UUID, content: str
) -> tuple[ChatSession, Lesson | None, AgentContext, Profile | None]:
    session = await get_owned(db, ChatSession, session_id, user, "Chat session")
    if not content:
        raise APIError(422, "Message content must not be empty", "EMPTY_MESSAGE")
    if len(content) > settings.max_message_chars:
        raise APIError(422, f"Message exceeds {settings.max_message_chars} characters", "MESSAGE_TOO_LONG")
    await check_and_record_user_limit(db, user.id, kind="chat")

    lesson = None
    if session.type == ChatSessionType.lesson:
        if not user.onboarding_complete:
            raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
        if session.lesson_id is None:
            raise APIError(404, "Lesson not found", "NOT_FOUND")
        lesson = await get_owned(db, Lesson, session.lesson_id, user, "Lesson")

    profile = await get_profile(db, user.id)
    context = AgentContext(
        user_id=user.id,
        db=db,
        call_type="chat",
        native_language=profile.native_language if profile else None,
        target_language=profile.target_language if profile else None,
        onboarding=lesson is None,
        session_id=session.id,
        lesson_id=lesson.id if lesson else None,
        lesson_number=lesson.lesson_number if lesson else None,
    )
    return session, lesson, context, profile


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_payload(item: StreamItem) -> dict:
    if item.kind == "token":
        return {"delta": item.data}
    if item.kind in ("tool_start", "tool_end"):
        return {"name": item.data}
    return item.data


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


def _trace_for(session: ChatSession, lesson: Lesson | None) -> dict:
    return {"session_type": session.type.value, "lesson_number": lesson.lesson_number if lesson else None}


async def _save_user_message(db: AsyncSession, session: ChatSession, content: str) -> None:
    db.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content=content))
    await db.commit()


async def _save_assistant(
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


def _log_llm_failure(exc: LLMError, user: User) -> None:
    logger.warning(
        "chat_llm_failed",
        extra={"event": "chat_llm_failed", "code": exc.code, "error": str(exc)[:500], "user_id": str(user.id)},
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatTurnResponse)
async def post_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatTurnResponse:
    """Non-streaming turn. Kept while `CHAT_STREAMING_ENABLED` is the rollback switch."""
    content = body.content.strip()
    session, lesson, context, profile = await _prepare_turn(db, user, session_id, content)
    agent = onboarding_agent(_checkpointer(request)) if lesson is None else lesson_agent(_checkpointer(request))

    async def save_user_message() -> None:
        await _save_user_message(db, session, content)

    try:
        reply = await metered_agent_run(
            db,
            user.id,
            "chat",
            agent=agent,
            user_text=content,
            context=context,
            thread_id=session.id,
            before_call=save_user_message,
            trace_metadata=_trace_for(session, lesson),
        )
    except LLMError as exc:
        _log_llm_failure(exc, user)
        raise APIError(_LLM_STATUS.get(exc.code, 502), public_detail(exc.code), exc.code) from exc

    message, metadata = await _save_assistant(db, user, session, lesson, profile, reply)
    return ChatTurnResponse(message_id=str(message.id), content=message.content, metadata=metadata)


@router.post("/sessions/{session_id}/messages/stream")
async def stream_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    if not settings.chat_streaming_enabled:
        raise APIError(404, "Streaming is not enabled", "STREAMING_DISABLED")
    content = body.content.strip()
    session, lesson, context, profile = await _prepare_turn(db, user, session_id, content)
    agent = onboarding_agent(_checkpointer(request)) if lesson is None else lesson_agent(_checkpointer(request))

    async def save_user_message() -> None:
        await _save_user_message(db, session, content)

    # Quota refusal must be the HTTP status. StreamingResponse commits 200
    # before its body runs, so the reserve finishes first.
    items = await metered_agent_stream(
        db,
        user.id,
        "chat",
        agent=agent,
        user_text=content,
        context=context,
        thread_id=session.id,
        before_call=save_user_message,
        trace_metadata=_trace_for(session, lesson),
    )

    async def events() -> AsyncIterator[str]:
        reply: OnboardingReply | LessonReply | None = None
        saw_token = False
        try:
            async for item in items:
                if item.kind == "structured":
                    reply = item.data
                    continue
                if item.kind == "token":
                    saw_token = True
                yield _sse(item.kind, _stream_payload(item))
        except LLMError as exc:
            _log_llm_failure(exc, user)
            yield _sse("error", {"code": exc.code, "detail": public_detail(exc.code)})
            return
        if reply is None:
            yield _sse(
                "error",
                {"code": "LLM_SCHEMA_ERROR", "detail": public_detail("LLM_SCHEMA_ERROR")},
            )
            return
        if settings.chat_stream_reply_fallback and not saw_token:
            yield _sse("token", {"delta": reply.content})
        yield _sse("structured", reply.model_dump(mode="json"))
        try:
            message, _metadata = await _save_assistant(db, user, session, lesson, profile, reply)
        except APIError as exc:
            yield _sse("error", {"code": exc.code, "detail": exc.detail})
            return
        yield _sse("done", {"message_id": str(message.id)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
