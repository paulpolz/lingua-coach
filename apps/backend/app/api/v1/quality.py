"""Authenticated quality events — thumbs and CSAT. Clerk auth, not telemetry.

`POST /api/v1/quality/events` returns 204. Judge kinds are server-written
(`evals/judge_online.py` and sampled candidates from lesson chat).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.quality import QualityEventCreate
from app.services.quality import (
    KIND_LESSON_CSAT,
    KIND_THUMBS,
    SOURCE_THUMBS_DOWN,
    add_judge_candidate,
    add_quality_event,
    compact_quality_snapshot,
    fetch_profile,
)
from app.services.rate_limit import check_and_record

logger = get_logger(__name__)

router = APIRouter(prefix="/quality", tags=["quality"])

_QUALITY_EVENTS_LIMIT_PER_HOUR = 60


async def _owned_lesson(db: AsyncSession, lesson_id: uuid.UUID, user: User) -> Lesson:
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None or lesson.user_id != user.id:
        raise APIError(404, "Lesson not found", "NOT_FOUND")
    return lesson


async def _owned_session_if_present(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> ChatSession | None:
    session = await db.get(ChatSession, session_id)
    if session is None:
        return None
    if session.user_id != user.id:
        raise APIError(404, "Chat session not found", "NOT_FOUND")
    return session


@router.post("/events", status_code=204)
async def create_quality_event(
    payload: QualityEventCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not check_and_record(f"quality_events:{user.id}", _QUALITY_EVENTS_LIMIT_PER_HOUR):
        raise APIError(
            status_code=429,
            detail="Quality event rate limit exceeded",
            code="RATE_LIMIT_EXCEEDED",
        )

    session_id = payload.session_id
    message_id = payload.message_id
    lesson_id = payload.lesson_id
    lesson: Lesson | None = None
    session: ChatSession | None = None
    message: ChatMessage | None = None

    if lesson_id is not None:
        lesson = await _owned_lesson(db, lesson_id, user)

    if session_id is not None:
        session = await _owned_session_if_present(db, session_id, user)
        if session is not None:
            if lesson_id is not None and session.lesson_id is not None and session.lesson_id != lesson_id:
                raise APIError(404, "Chat session not found", "NOT_FOUND")
            if lesson is None and session.lesson_id is not None:
                lesson = await _owned_lesson(db, session.lesson_id, user)
                lesson_id = lesson.id

    if message_id is not None:
        result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
        message = result.scalar_one_or_none()
        if message is not None:
            msg_session = await db.get(ChatSession, message.session_id)
            if msg_session is None or msg_session.user_id != user.id:
                raise APIError(404, "Chat session not found", "NOT_FOUND")
            if session_id is not None and message.session_id != session_id:
                raise APIError(404, "Chat session not found", "NOT_FOUND")
            session = msg_session
            session_id = msg_session.id
            if lesson is None and msg_session.lesson_id is not None:
                lesson = await _owned_lesson(db, msg_session.lesson_id, user)
                lesson_id = lesson.id

    if payload.kind == KIND_THUMBS:
        stored_value: dict = {"thumb": int(payload.value["thumb"])}
        if message is not None:
            profile = await fetch_profile(db, user.id)
            stored_value["snapshot"] = compact_quality_snapshot(
                assistant_text=message.content or "",
                profile=profile,
                lesson=lesson,
            )
        add_quality_event(
            db,
            user_id=user.id,
            kind=KIND_THUMBS,
            surface=payload.surface,
            session_id=session_id,
            message_id=message_id,
            lesson_id=lesson_id,
            value=stored_value,
            metric_value=str(int(payload.value["thumb"])),
        )
        if int(payload.value["thumb"]) == -1:
            snapshot = stored_value.get("snapshot")
            if isinstance(snapshot, dict):
                await add_judge_candidate(
                    db,
                    user_id=user.id,
                    surface=payload.surface,
                    session_id=session_id,
                    message_id=message_id,
                    lesson_id=lesson_id,
                    snapshot=snapshot,
                    source=SOURCE_THUMBS_DOWN,
                )
        logger.info(
            "quality_event",
            extra={
                "event": "quality_event",
                "kind": KIND_THUMBS,
                "surface": payload.surface,
                "user_id": str(user.id),
                "session_id": str(session_id) if session_id else None,
                "message_id": str(message_id) if message_id else None,
                "lesson_id": str(lesson_id) if lesson_id else None,
                "thumb": int(payload.value["thumb"]),
                "has_snapshot": "snapshot" in stored_value,
            },
        )
    else:
        csat = int(payload.value["csat"])
        add_quality_event(
            db,
            user_id=user.id,
            kind=KIND_LESSON_CSAT,
            surface=payload.surface,
            session_id=session_id,
            message_id=message_id,
            lesson_id=lesson_id,
            value={"csat": csat},
            metric_value=str(csat),
        )
        logger.info(
            "quality_event",
            extra={
                "event": "quality_event",
                "kind": KIND_LESSON_CSAT,
                "surface": payload.surface,
                "user_id": str(user.id),
                "lesson_id": str(lesson_id) if lesson_id else None,
                "csat": csat,
            },
        )

    await db.commit()
    return Response(status_code=204)
