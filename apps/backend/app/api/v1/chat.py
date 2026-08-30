"""Chat sessions + SSE messages.

`POST /chat/sessions`, `POST /chat/sessions/{id}/messages` (SSE),
`GET /chat/sessions/{id}/messages` — docs/implementation-readiness.md §6-7.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

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
    ChatDoneMetadata,
    ChatMessageCreateRequest,
    ChatMessageOut,
    ChatMessagesListResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    CorrectionItem,
    LessonMistakeItem,
    PlanUpdates,
)
from app.schemas.learner_profile import LearnerProfile
from app.services import extraction
from app.services.gemini import ChatTurn, GeminiError, stream_chat
from app.services.languages import normalize_language
from app.services.prompt_assembly import (
    lesson_curriculum_snippet_from_payload,
    lesson_profile_block_from_snapshot,
    lesson_system_instruction,
    onboarding_system_instruction,
)
from app.services.quality import maybe_write_lesson_turn_candidate
from app.services.rate_limit import check_and_record
from app.services.skills import should_include_vocab_formats

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Spaced-repetition schedule for `mistakes.next_review_at`, keyed by the
# occurrence count *after* this write (skills/exercise_tutor.md "When the
# learner errs" step 4: "+1, +3, +7, +14 days"). Occurrence counts beyond the
# table cap at the longest interval.
_SPACED_REPETITION_DAYS = {1: 1, 2: 3, 3: 7}
_SPACED_REPETITION_MAX_DAYS = 14

# Most-recent open mistakes surfaced in the lesson-chat profile context block
# — a short list, not a full dump (ai-api.md "compact learner profile").
_DUE_MISTAKES_LIMIT = 10


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _get_owned_session(db: AsyncSession, session_id: str, user: User) -> ChatSession:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise APIError(404, "Chat session not found", "NOT_FOUND") from None
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_uuid))
    session = result.scalar_one_or_none()
    if session is None or session.user_id != user.id:
        raise APIError(404, "Chat session not found", "NOT_FOUND")
    return session


async def _get_owned_lesson(db: AsyncSession, lesson_id: str, user: User) -> Lesson:
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise APIError(404, "Lesson not found", "NOT_FOUND") from None
    lesson = await db.get(Lesson, lesson_uuid)
    if lesson is None or lesson.user_id != user.id:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    return lesson


async def _get_lesson_for_session(db: AsyncSession, session: ChatSession, user: User) -> Lesson:
    if session.lesson_id is None:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    lesson = await db.get(Lesson, session.lesson_id)
    if lesson is None or lesson.user_id != user.id:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    return lesson


async def _fetch_onboarding_session(db: AsyncSession, user_id: uuid.UUID) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.type == ChatSessionType.onboarding,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_lesson_session(
    db: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.type == ChatSessionType.lesson,
            ChatSession.lesson_id == lesson_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_or_create_onboarding_session(db: AsyncSession, user: User) -> ChatSession:
    """One onboarding session per user — enforced by partial unique index + upsert.

    `index_where` must be the same SQL as the unique index predicate
    (`type = 'onboarding'`). A bound enum (`type = $1::chat_session_type`)
    does not match, and Postgres raises InvalidColumnReferenceError.
    """
    existing = await _fetch_onboarding_session(db, user.id)
    if existing is not None:
        return existing

    stmt = (
        insert(ChatSession)
        .values(user_id=user.id, type=ChatSessionType.onboarding, lesson_id=None)
        .on_conflict_do_nothing(
            index_elements=["user_id"],
            index_where=text("type = 'onboarding'"),
        )
        .returning(ChatSession.id)
    )
    result = await db.execute(stmt)
    new_id = result.scalar_one_or_none()
    await db.commit()

    if new_id is not None:
        session = await db.get(ChatSession, new_id)
        assert session is not None
        return session

    session = await _fetch_onboarding_session(db, user.id)
    if session is None:
        raise RuntimeError("onboarding chat session missing after upsert conflict")
    return session


async def _get_or_create_lesson_session(
    db: AsyncSession, user: User, lesson: Lesson
) -> ChatSession:
    """One lesson chat session per (user, lesson) — enforced by partial unique index + upsert."""
    existing = await _fetch_lesson_session(db, user.id, lesson.id)
    if existing is not None:
        return existing

    stmt = (
        insert(ChatSession)
        .values(
            user_id=user.id,
            type=ChatSessionType.lesson,
            lesson_id=lesson.id,
        )
        .on_conflict_do_nothing(
            index_elements=["user_id", "lesson_id"],
            index_where=text("type = 'lesson' AND lesson_id IS NOT NULL"),
        )
        .returning(ChatSession.id)
    )
    result = await db.execute(stmt)
    new_id = result.scalar_one_or_none()
    await db.commit()

    if new_id is not None:
        session = await db.get(ChatSession, new_id)
        assert session is not None
        return session

    session = await _fetch_lesson_session(db, user.id, lesson.id)
    if session is None:
        raise RuntimeError("lesson chat session missing after upsert conflict")
    return session


@router.post("/sessions", status_code=201, response_model=ChatSessionResponse)
async def create_chat_session(
    body: ChatSessionCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    if body.type == "onboarding":
        session = await _get_or_create_onboarding_session(db, user)
        return ChatSessionResponse(id=str(session.id), type="onboarding", lesson_id=None)

    # type == "lesson"
    if not body.lesson_id:
        raise APIError(422, "lesson_id is required for type=lesson", "LESSON_ID_REQUIRED")
    # Defensive/consistent with the onboarding gate on lesson routes — a
    # lesson can't exist for a non-onboarded user anyway (POST /lessons/start
    # requires it), but this keeps the error shape uniform if that ever
    # changes.
    if not user.onboarding_complete:
        raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")

    lesson = await _get_owned_lesson(db, body.lesson_id, user)
    if lesson.status not in (LessonStatus.generating, LessonStatus.active):
        raise APIError(
            409,
            f"Lesson is {lesson.status.value}; chat is only available while a lesson is "
            "generating or active",
            "LESSON_NOT_ACTIVE",
        )

    session = await _get_or_create_lesson_session(db, user, lesson)
    return ChatSessionResponse(id=str(session.id), type="lesson", lesson_id=str(lesson.id))


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesListResponse)
async def list_chat_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessagesListResponse:
    session = await _get_owned_session(db, session_id, user)
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    return ChatMessagesListResponse(
        messages=[
            ChatMessageOut(
                id=str(m.id),
                role=m.role.value,
                content=m.content,
                created_at=m.created_at,
                metadata=m.metadata_json,
            )
            for m in messages
        ]
    )


async def _persist_learner_profile(db: AsyncSession, user: User, learner_profile: LearnerProfile) -> None:
    """Onboarding interview complete → upsert `profiles` + draft `learning_goals`
    per database.md's "Onboarding data flow". Idempotent — safe to call again
    if the model re-emits a revised profile on a later refinement turn."""
    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = Profile(user_id=user.id, pace_window_hours=settings.pace_window_hours)
        db.add(profile)

    profile.goal_outcome = learner_profile.goal.outcome
    profile.goal_horizon = learner_profile.goal.horizon
    profile.goal_success_criteria = learner_profile.goal.success_criteria
    profile.native_language = normalize_language(learner_profile.languages.native)
    profile.target_language = normalize_language(learner_profile.languages.target)
    profile.target_level = learner_profile.level.self_assessed
    profile.level_strengths = learner_profile.level.strengths
    profile.level_weaknesses = learner_profile.level.weaknesses
    profile.diagnostic_notes = learner_profile.level.diagnostic_notes
    profile.time_budget = learner_profile.time_budget.model_dump()
    profile.focus = learner_profile.focus.model_dump()
    profile.constraints = learner_profile.constraints.model_dump()
    profile.motivation = learner_profile.motivation.model_dump()
    profile.interview_completed_at = now

    goal_result = await db.execute(
        select(LearningGoal).where(
            LearningGoal.user_id == user.id, LearningGoal.status == LearningGoalStatus.draft
        )
    )
    goal = goal_result.scalar_one_or_none()
    if goal is None:
        goal = LearningGoal(user_id=user.id, status=LearningGoalStatus.draft)
        db.add(goal)
    goal.goal_statement = learner_profile.goal.outcome
    goal.horizon = learner_profile.goal.horizon
    goal.success_criteria = learner_profile.goal.success_criteria

    await db.commit()


def _next_review_at(occurrence_count: int, now: datetime) -> datetime:
    """Spaced-repetition schedule per skills/exercise_tutor.md ("+1, +3, +7,
    +14 days"), keyed by occurrence count after this write; caps at the
    longest interval for repeat offenders beyond the table."""
    days = _SPACED_REPETITION_DAYS.get(occurrence_count, _SPACED_REPETITION_MAX_DAYS)
    return now + timedelta(days=days)


async def _upsert_mistake(
    db: AsyncSession, *, user: User, lesson: Lesson, item: LessonMistakeItem
) -> None:
    """database.md "mistakes" upsert rule: same `user_id` + `pattern_type` →
    increment `occurrence_count`, refresh `example_text`/`lesson_id`/
    `last_seen_at`, recompute `next_review_at`; else create with
    `occurrence_count=1`."""
    result = await db.execute(
        select(Mistake).where(Mistake.user_id == user.id, Mistake.pattern_type == item.pattern_type)
    )
    mistake = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if mistake is None:
        db.add(
            Mistake(
                user_id=user.id,
                lesson_id=lesson.id,
                pattern_type=item.pattern_type,
                example_text=item.example_text,
                correction=item.correction,
                occurrence_count=1,
                next_review_at=_next_review_at(1, now),
                last_seen_at=now,
            )
        )
        return

    mistake.occurrence_count += 1
    mistake.example_text = item.example_text
    if item.correction is not None:
        mistake.correction = item.correction
    mistake.lesson_id = lesson.id
    mistake.last_seen_at = now
    mistake.next_review_at = _next_review_at(mistake.occurrence_count, now)


async def _apply_lesson_plan_updates(db: AsyncSession, *, user: User, plan_updates: PlanUpdates) -> None:
    """backend.md "Plan adaptation (chat-only)": validated `plan_updates`
    patch `profiles` fields directly (no plan-editor API). Recompute
    `projected_completion_at` when `target_plan_days` changes (backend.md
    "Plan schedule and pacing": "remaining plan days × PACE_WINDOW_HOURS"),
    and log a `progress_events` row for audit/debug."""
    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        # Shouldn't happen once onboarded, but never fail the chat turn.
        return

    changed_fields: dict = {}

    if plan_updates.goal_summary is not None:
        profile.goal_outcome = plan_updates.goal_summary
        changed_fields["goal_summary"] = plan_updates.goal_summary
    if plan_updates.level is not None:
        profile.target_level = plan_updates.level
        changed_fields["level"] = plan_updates.level
    if plan_updates.time_budget is not None:
        profile.time_budget = plan_updates.time_budget
        changed_fields["time_budget"] = plan_updates.time_budget
    if plan_updates.topics is not None:
        focus = dict(profile.focus or {})
        focus["topic_priorities"] = plan_updates.topics
        profile.focus = focus
        changed_fields["topics"] = plan_updates.topics
    if plan_updates.vocab_priorities is not None:
        focus = dict(profile.focus or {})
        focus["vocab_priorities"] = plan_updates.vocab_priorities
        profile.focus = focus
        changed_fields["vocab_priorities"] = plan_updates.vocab_priorities
    if plan_updates.grammar_mastery is not None:
        grammar_mastery = dict(profile.grammar_mastery or {})
        grammar_mastery.update(plan_updates.grammar_mastery)
        profile.grammar_mastery = grammar_mastery
        changed_fields["grammar_mastery"] = plan_updates.grammar_mastery
    if plan_updates.target_plan_days is not None and plan_updates.target_plan_days != profile.target_plan_days:
        profile.target_plan_days = plan_updates.target_plan_days
        changed_fields["target_plan_days"] = plan_updates.target_plan_days

        plan_days_done = (
            await db.scalar(
                select(func.count())
                .select_from(Lesson)
                .where(Lesson.user_id == user.id, Lesson.status == LessonStatus.accomplished)
            )
            or 0
        )
        remaining_days = max(plan_updates.target_plan_days - plan_days_done, 0)
        pace_window_hours = profile.pace_window_hours or settings.pace_window_hours
        profile.projected_completion_at = datetime.now(timezone.utc) + timedelta(
            hours=remaining_days * pace_window_hours
        )

    if changed_fields:
        db.add(
            ProgressEvent(
                user_id=user.id,
                event_type="plan_updated",
                payload=changed_fields,
            )
        )


def _lesson_curriculum_snippet(lesson: Lesson) -> str:
    """Compact "current lesson curriculum" block for `contents` (ai-api.md
    "Chat / correction": "current lesson snippet (lesson mode)") — the
    lesson_goal/grammar_focus/vocab_theme/slots/exit_criteria fields from
    `lessons.payload.curriculum`, not a full chat-history dump."""
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    return lesson_curriculum_snippet_from_payload(curriculum)


async def _fetch_profile(db: AsyncSession, user: User) -> Profile | None:
    result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    return result.scalar_one_or_none()


async def _lesson_profile_block(
    db: AsyncSession, user: User, *, profile: Profile | None = None
) -> str:
    """Compact learner-profile context block (languages/goal/level + weak
    patterns due for review) — a short text block is sufficient for MVP."""
    if profile is None:
        profile = await _fetch_profile(db, user)

    now = datetime.now(timezone.utc)
    mistakes_result = await db.execute(
        select(Mistake)
        .where(Mistake.user_id == user.id, Mistake.next_review_at <= now)
        .order_by(Mistake.next_review_at)
        .limit(_DUE_MISTAKES_LIMIT)
    )
    due_mistakes = mistakes_result.scalars().all()

    goal = profile.goal_outcome if profile and profile.goal_outcome else "(not set)"
    level = profile.target_level if profile and profile.target_level else "(not set)"
    native = profile.native_language if profile and profile.native_language else "(not set)"
    target = profile.target_language if profile and profile.target_language else "en"

    return lesson_profile_block_from_snapshot(native, target, goal, level, due_mistakes)


async def _load_context_history(db: AsyncSession, session: ChatSession) -> list[ChatTurn]:
    context_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(settings.chat_context_messages)
    )
    context_messages = list(reversed(context_result.scalars().all()))
    return [
        ChatTurn(role="model" if m.role == ChatMessageRole.assistant else "user", text=m.content)
        for m in context_messages
    ]


async def _onboarding_event_stream(
    *, db: AsyncSession, user: User, session: ChatSession, history: list[ChatTurn]
) -> AsyncGenerator[str, None]:
    profile = await _fetch_profile(db, user)
    system_instruction = onboarding_system_instruction(
        profile.native_language if profile else None,
        profile.target_language if profile else None,
    )

    full_text_parts: list[str] = []
    try:
        async for chunk in stream_chat(system_instruction=system_instruction, history=history):
            full_text_parts.append(chunk)
            yield _sse("token", {"text": chunk})
    except GeminiError as exc:
        yield _sse("error", {"code": exc.code, "message": str(exc)})
        return

    raw_text = "".join(full_text_parts)
    clean_text = extraction.strip_structured_blocks(raw_text)

    learner_profile = extraction.extract_learner_profile(raw_text)
    roadmap_draft = extraction.extract_course_roadmap(raw_text)

    plan_updates: PlanUpdates | None = None
    if learner_profile is not None:
        try:
            await _persist_learner_profile(db, user, learner_profile)
            plan_updates = PlanUpdates(
                goal_summary=learner_profile.goal.outcome, level=learner_profile.level.self_assessed
            )
        except SQLAlchemyError:
            logger.warning(
                "onboarding_profile_persist_failed",
                exc_info=True,
                extra={
                    "event": "db_persist_failed",
                    "surface": "onboarding",
                    "user_id": str(user.id),
                    "session_id": str(session.id),
                },
            )
            await db.rollback()
            yield _sse(
                "error",
                {
                    "code": "PROFILE_PERSIST_FAILED",
                    "message": "Could not save your learning profile. Please try again.",
                },
            )
            return

    done_metadata = ChatDoneMetadata(
        corrections=[],
        tips=[],
        plan_updates=plan_updates,
        suggest_finish=False,
        course_roadmap_draft=roadmap_draft,
        lesson_plan=None,
        task_update=None,
    )
    assistant_message = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.assistant,
        content=clean_text,
        metadata_json=json.loads(done_metadata.model_dump_json()),
    )
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)
    yield _sse(
        "done",
        {
            "message_id": str(assistant_message.id),
            "content": clean_text,
            "metadata": json.loads(done_metadata.model_dump_json()),
        },
    )


async def _lesson_event_stream(
    *, db: AsyncSession, user: User, session: ChatSession, lesson: Lesson, history: list[ChatTurn]
) -> AsyncGenerator[str, None]:
    profile = await _fetch_profile(db, user)
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    include_vocab = should_include_vocab_formats(curriculum)
    system_instruction = lesson_system_instruction(
        profile.native_language if profile else None,
        profile.target_language if profile else None,
        include_vocab,
    )

    # ai-api.md "Prompt assembly": contents <- profile/plan block + message
    # history + new turn. `history` already ends with the new user turn, so
    # the curriculum/profile context block is prepended as a leading turn.
    context_block = (
        f"{_lesson_curriculum_snippet(lesson)}\n\n"
        f"{await _lesson_profile_block(db, user, profile=profile)}"
    )
    contents = [ChatTurn(role="user", text=context_block), *history]

    full_text_parts: list[str] = []
    try:
        async for chunk in stream_chat(system_instruction=system_instruction, history=contents):
            full_text_parts.append(chunk)
            yield _sse("token", {"text": chunk})
    except GeminiError as exc:
        yield _sse("error", {"code": exc.code, "message": str(exc)})
        return

    raw_text = "".join(full_text_parts)
    clean_text = extraction.strip_structured_blocks(raw_text)
    turn = extraction.extract_lesson_turn(raw_text)

    corrections: list[CorrectionItem] = turn.corrections if turn else []
    tips: list[str] = turn.tips if turn else []
    plan_updates: PlanUpdates | None = turn.plan_updates if turn else None
    suggest_finish: bool = turn.suggest_finish if turn else False
    mistakes: list[LessonMistakeItem] = turn.mistakes if turn else []
    lesson_plan = extraction.extract_lesson_plan(raw_text)
    task_update = extraction.extract_task_update(raw_text)

    try:
        for item in mistakes:
            await _upsert_mistake(db, user=user, lesson=lesson, item=item)
        if plan_updates is not None:
            await _apply_lesson_plan_updates(db, user=user, plan_updates=plan_updates)
        await db.commit()
    except SQLAlchemyError:
        logger.warning(
            "lesson_metadata_persist_failed",
            exc_info=True,
            extra={
                "event": "db_persist_failed",
                "surface": "lesson",
                "user_id": str(user.id),
                "session_id": str(session.id),
                "lesson_id": str(lesson.id),
            },
        )
        await db.rollback()
        yield _sse(
            "error",
            {
                "code": "LESSON_PERSIST_FAILED",
                "message": "Could not save lesson progress. Please try again.",
            },
        )
        return

    done_metadata = ChatDoneMetadata(
        corrections=corrections,
        tips=tips,
        plan_updates=plan_updates,
        suggest_finish=suggest_finish,
        course_roadmap_draft=None,
        lesson_plan=lesson_plan,
        task_update=task_update,
    )
    assistant_message = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.assistant,
        content=clean_text,
        metadata_json=json.loads(done_metadata.model_dump_json()),
    )
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)
    await maybe_write_lesson_turn_candidate(
        db,
        user=user,
        session=session,
        lesson=lesson,
        message=assistant_message,
        corrections=corrections,
        profile=profile,
    )
    yield _sse(
        "done",
        {
            "message_id": str(assistant_message.id),
            "content": clean_text,
            "metadata": json.loads(done_metadata.model_dump_json()),
        },
    )


@router.post("/sessions/{session_id}/messages")
async def post_chat_message(
    session_id: str,
    body: ChatMessageCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    session = await _get_owned_session(db, session_id, user)

    content = body.content.strip()
    if not content:
        raise APIError(422, "Message content must not be empty", "EMPTY_MESSAGE")
    if len(content) > settings.max_message_chars:
        raise APIError(
            422, f"Message exceeds {settings.max_message_chars} characters", "MESSAGE_TOO_LONG"
        )
    if not check_and_record(f"chat:{user.id}", settings.chat_rate_limit_per_hour):
        raise APIError(429, "Chat rate limit exceeded", "RATE_LIMIT_EXCEEDED")

    lesson: Lesson | None = None
    if session.type == ChatSessionType.lesson:
        if not user.onboarding_complete:
            raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
        lesson = await _get_lesson_for_session(db, session, user)

    user_message = ChatMessage(session_id=session.id, role=ChatMessageRole.user, content=content)
    db.add(user_message)
    await db.commit()

    history = await _load_context_history(db, session)

    if session.type == ChatSessionType.onboarding:
        event_stream = _onboarding_event_stream(db=db, user=user, session=session, history=history)
    else:
        assert lesson is not None
        event_stream = _lesson_event_stream(
            db=db, user=user, session=session, lesson=lesson, history=history
        )

    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
