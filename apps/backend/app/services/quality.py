"""Persist online quality events and compact judge snapshots.

Never stores the full Gemini prompt. Assistant text is truncated. Failures
here must not break chat SSE or lesson finish.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import record_quality_event
from app.models.chat import ChatMessage, ChatSession
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.quality_event import QualityEvent
from app.models.user import User

logger = get_logger(__name__)

CORRECTION_SAMPLE_PERCENT = 10
_SNAPSHOT_TEXT_MAX = 8000
_SNIPPET_FIELD_MAX = 240

KIND_THUMBS = "thumbs"
KIND_LESSON_CSAT = "lesson_csat"
KIND_JUDGE = "judge"
KIND_JUDGE_CANDIDATE = "judge_candidate"

SOURCE_CORRECTIONS_SAMPLE = "corrections_sample"
SOURCE_THUMBS_DOWN = "thumbs_down"


def should_sample_correction_turn(message_id: uuid.UUID) -> bool:
    """Stable ~10% sample from message id (not per-request random)."""
    return message_id.int % 100 < CORRECTION_SAMPLE_PERCENT


def compact_lesson_snippet(lesson: Lesson | None) -> dict[str, Any] | None:
    if lesson is None:
        return None
    curriculum = (lesson.payload or {}).get("curriculum") or {}
    if not isinstance(curriculum, dict) or not curriculum:
        return None
    return {
        "lesson_goal": str(curriculum.get("lesson_goal") or "")[:_SNIPPET_FIELD_MAX],
        "grammar_focus": str(curriculum.get("grammar_focus") or "")[:_SNIPPET_FIELD_MAX],
        "vocab_theme": str(curriculum.get("vocab_theme") or "")[:_SNIPPET_FIELD_MAX],
        "milestone_index": curriculum.get("milestone_index"),
    }


def compact_quality_snapshot(
    *,
    assistant_text: str,
    profile: Profile | None,
    lesson: Lesson | None,
) -> dict[str, Any]:
    return {
        "assistant_text": (assistant_text or "")[:_SNAPSHOT_TEXT_MAX],
        "native": profile.native_language if profile else None,
        "target": profile.target_language if profile else None,
        "goal": profile.goal_outcome if profile else None,
        "level": profile.target_level if profile else None,
        "lesson_snippet": compact_lesson_snippet(lesson),
    }


async def fetch_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    return result.scalar_one_or_none()


async def candidate_exists_for_message(db: AsyncSession, message_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(QualityEvent.id).where(
            QualityEvent.kind == KIND_JUDGE_CANDIDATE,
            QualityEvent.message_id == message_id,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def add_quality_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    surface: str,
    session_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
    lesson_id: uuid.UUID | None,
    value: dict[str, Any],
    metric_value: str | None = None,
) -> QualityEvent:
    event = QualityEvent(
        user_id=user_id,
        kind=kind,
        surface=surface,
        session_id=session_id,
        message_id=message_id,
        lesson_id=lesson_id,
        value=value,
    )
    db.add(event)
    if metric_value is not None:
        record_quality_event(kind=kind, surface=surface, value=metric_value)
    return event


def add_lesson_csat(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_id: uuid.UUID | None,
    csat: int,
) -> QualityEvent:
    return add_quality_event(
        db,
        user_id=user.id,
        kind=KIND_LESSON_CSAT,
        surface="lesson",
        session_id=session_id,
        message_id=None,
        lesson_id=lesson.id,
        value={"csat": csat},
        metric_value=str(csat),
    )


async def add_judge_candidate(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    surface: str,
    session_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
    lesson_id: uuid.UUID | None,
    snapshot: dict[str, Any],
    source: str,
) -> QualityEvent | None:
    if message_id is not None and await candidate_exists_for_message(db, message_id):
        return None
    return add_quality_event(
        db,
        user_id=user_id,
        kind=KIND_JUDGE_CANDIDATE,
        surface=surface,
        session_id=session_id,
        message_id=message_id,
        lesson_id=lesson_id,
        value={"snapshot": snapshot, "source": source},
    )


async def maybe_write_lesson_turn_candidate(
    db: AsyncSession,
    *,
    user: User,
    session: ChatSession,
    lesson: Lesson,
    message: ChatMessage,
    corrections: list[Any],
    profile: Profile | None,
) -> None:
    """~10% of lesson turns that have corrections. Never calls Gemini."""
    if not corrections:
        return
    if not should_sample_correction_turn(message.id):
        return
    try:
        snapshot = compact_quality_snapshot(
            assistant_text=message.content or "",
            profile=profile,
            lesson=lesson,
        )
        await add_judge_candidate(
            db,
            user_id=user.id,
            surface="lesson",
            session_id=session.id,
            message_id=message.id,
            lesson_id=lesson.id,
            snapshot=snapshot,
            source=SOURCE_CORRECTIONS_SAMPLE,
        )
        await db.commit()
    except Exception:
        logger.warning(
            "quality_candidate_write_failed",
            exc_info=True,
            extra={
                "event": "quality_candidate_write_failed",
                "surface": "lesson",
                "user_id": str(user.id),
                "session_id": str(session.id),
                "message_id": str(message.id),
            },
        )
        await db.rollback()
