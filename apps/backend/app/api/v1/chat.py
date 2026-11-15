"""Chat sessions and the streamed coach turn for onboarding and lessons."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import get_current_user, get_owned
from app.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatSessionType, LessonStatus
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.schemas.chat import (
    ChatMessageCreateRequest,
    ChatMessageOut,
    ChatMessagesListResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
)
from app.schemas.llm import LessonReply, OnboardingReply
from app.services.agents.catalog import lesson_agent, onboarding_agent
from app.services.agents.runner import LLMError, StreamItem, metered_agent_stream, public_detail
from app.services.agents.tools import AgentContext
from app.services.chat_turns import save_assistant, save_user_message
from app.services.llm_usage import check_and_record_user_limit
from app.services.queries import get_profile

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


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


def _trace_for(session: ChatSession, lesson: Lesson | None) -> dict:
    return {"session_type": session.type.value, "lesson_number": lesson.lesson_number if lesson else None}


def _log_llm_failure(exc: LLMError, user: User) -> None:
    logger.warning(
        "chat_llm_failed",
        extra={"event": "chat_llm_failed", "code": exc.code, "error": str(exc)[:500], "user_id": str(user.id)},
    )


@router.post("/sessions/{session_id}/messages/stream")
async def stream_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    content = body.content.strip()
    session, lesson, context, profile = await _prepare_turn(db, user, session_id, content)
    agent = onboarding_agent(_checkpointer(request)) if lesson is None else lesson_agent(_checkpointer(request))

    async def save_user() -> None:
        await save_user_message(db, session, content)

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
        before_call=save_user,
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
            message, _metadata = await save_assistant(db, user, session, lesson, profile, reply)
        except APIError as exc:
            yield _sse("error", {"code": exc.code, "detail": exc.detail})
            return
        yield _sse("done", {"message_id": str(message.id)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
