"""DB-backed chat, lesson-start, and global Gemini limits.

Per-user chat (rolling hour) counts `call_type='chat'` rows written by
`reserve_gemini_call`. Per-user lesson starts (rolling 24h) are
`call_type='lesson_start'` rows, one per HTTP start. Global RPM, input TPM,
and RPD count Gemini calls only (`chat`, `lesson_json`, `report`), including
`reserved` and `error` rows. Windows are 60s / 3600s / 86400s.

Rows are committed on a side session so a caller's open transaction (lesson
finish, in particular) is not committed early, and in-flight reservations are
visible to the next request.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import APIError
from app.models.llm_usage import LlmUsageEvent

GeminiCallType = Literal["chat", "lesson_json", "report"]
UserLimitKind = Literal["chat", "lesson_start"]
UsageStatus = Literal["ok", "error"]

_GEMINI_CALL_TYPES = ("chat", "lesson_json", "report")
_MINUTE_SECONDS = 60
_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400


def estimate_input_tokens(*parts: str) -> int:
    """Rough pre-flight input size: 4 characters per token."""
    return sum(len(part) for part in parts) // 4


def _retry_after(oldest: datetime | None, window_seconds: int, *, fixed: int | None = None) -> int:
    if fixed is not None:
        return fixed
    if oldest is None:
        return window_seconds
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - oldest).total_seconds()
    return max(1, int(window_seconds - elapsed))


def _limit_error(detail: str, code: str, retry_after: int) -> APIError:
    return APIError(429, detail, code, headers={"Retry-After": str(retry_after)})


@asynccontextmanager
async def _side_session(db: AsyncSession):
    bind = db.bind
    if bind is None:
        raise RuntimeError("database session is not bound")
    side = AsyncSession(bind, expire_on_commit=False)
    try:
        yield side
    finally:
        await side.close()


async def _window_stats(
    db: AsyncSession,
    *,
    window_seconds: int,
    user_id: uuid.UUID | None = None,
    call_types: tuple[str, ...] | None = None,
) -> tuple[int, int, datetime | None]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    stmt = select(
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.min(LlmUsageEvent.created_at),
    ).where(LlmUsageEvent.created_at >= cutoff)
    if user_id is not None:
        stmt = stmt.where(LlmUsageEvent.user_id == user_id)
    if call_types is not None:
        stmt = stmt.where(LlmUsageEvent.call_type.in_(call_types))
    count, tokens, oldest = (await db.execute(stmt)).one()
    return int(count), int(tokens), oldest


async def _insert_event(db: AsyncSession, event: LlmUsageEvent) -> LlmUsageEvent:
    async with _side_session(db) as side:
        side.add(event)
        await side.commit()
        # Detach before close so callers can read id/tokens after the session ends.
        side.expunge(event)
    return event


async def check_and_record_user_limit(
    db: AsyncSession, user_id: uuid.UUID, *, kind: UserLimitKind
) -> None:
    """Enforce the per-user chat hour or lesson-start day bucket.

    Chat is checked against Gemini `chat` rows (recorded by the following
    `reserve_gemini_call`). A lesson start inserts one `lesson_start` row.
    Raises `429 RATE_LIMIT_EXCEEDED` with `Retry-After` when the bucket is full.
    """
    if kind == "chat":
        window = _HOUR_SECONDS
        limit = settings.chat_rate_limit_per_hour
        call_types: tuple[str, ...] = ("chat",)
        detail = "Chat rate limit exceeded"
    else:
        window = _DAY_SECONDS
        limit = settings.lesson_start_rate_limit_per_day
        call_types = ("lesson_start",)
        detail = "Lesson start rate limit exceeded"

    count, _, oldest = await _window_stats(
        db, window_seconds=window, user_id=user_id, call_types=call_types
    )
    if count >= limit:
        raise _limit_error(detail, "RATE_LIMIT_EXCEEDED", _retry_after(oldest, window))

    if kind == "lesson_start":
        await _insert_event(
            db,
            LlmUsageEvent(
                user_id=user_id,
                call_type="lesson_start",
                input_tokens=0,
                status="ok",
            ),
        )


async def reserve_gemini_call(
    db: AsyncSession,
    user_id: uuid.UUID,
    call_type: GeminiCallType,
    *,
    estimated_input_tokens: int,
) -> LlmUsageEvent:
    """Pre-flight global RPM, RPD, and input TPM, then insert `reserved`.

    TPM is the sum of `input_tokens` already in the rolling minute plus
    `estimated_input_tokens` for this prompt. Raises `429 LLM_RATE_LIMIT_EXCEEDED`
    with `Retry-After` (60s for RPM/TPM, remaining time in the 24h window for RPD).
    """
    minute_count, minute_tokens, _minute_oldest = await _window_stats(
        db, window_seconds=_MINUTE_SECONDS, call_types=_GEMINI_CALL_TYPES
    )
    if minute_count >= settings.llm_rpm_limit:
        raise _limit_error(
            "LLM rate limit exceeded",
            "LLM_RATE_LIMIT_EXCEEDED",
            _retry_after(None, _MINUTE_SECONDS, fixed=_MINUTE_SECONDS),
        )

    day_count, _, day_oldest = await _window_stats(
        db, window_seconds=_DAY_SECONDS, call_types=_GEMINI_CALL_TYPES
    )
    if day_count >= settings.llm_rpd_limit:
        raise _limit_error(
            "LLM rate limit exceeded",
            "LLM_RATE_LIMIT_EXCEEDED",
            _retry_after(day_oldest, _DAY_SECONDS),
        )

    if minute_tokens + estimated_input_tokens > settings.llm_input_tpm_limit:
        raise _limit_error(
            "LLM rate limit exceeded",
            "LLM_RATE_LIMIT_EXCEEDED",
            _retry_after(None, _MINUTE_SECONDS, fixed=_MINUTE_SECONDS),
        )

    return await _insert_event(
        db,
        LlmUsageEvent(
            user_id=user_id,
            call_type=call_type,
            input_tokens=estimated_input_tokens,
            status="reserved",
        ),
    )


async def complete(
    db: AsyncSession,
    event: LlmUsageEvent,
    *,
    input_tokens: int,
    status: UsageStatus,
    model: str | None,
) -> None:
    """Mark a reserved call `ok` or `error`. Actual input tokens are written on `ok`."""
    async with _side_session(db) as side:
        row = await side.get(LlmUsageEvent, event.id)
        if row is None:
            return
        row.status = status
        row.model = model
        if status == "ok":
            row.input_tokens = input_tokens
        await side.commit()
    event.status = status
    event.model = model
    if status == "ok":
        event.input_tokens = input_tokens
