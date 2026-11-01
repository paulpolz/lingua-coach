"""DB-backed chat, lesson-start, and global LLM limits.

Per-user chat (rolling hour) counts `call_type='chat'` rows written by
`reserve_llm_call`. Per-user lesson starts (rolling 24h) are
`call_type='lesson_start'` rows, one per HTTP start. Global RPM, input TPM,
and RPD count Gemini calls only (`chat`, `lesson_json`, `report`), including
`reserved` and `error` rows. Windows are 60s / 3600s / 86400s.

Rows are committed on a side session so a caller's open transaction is not
committed early, and in-flight reservations are visible to the next request.

These are soft limits: check-then-insert is not atomic across processes, so two
concurrent requests can both pass a nearly full window. That is acceptable for
protecting a provider quota; it is not a billing boundary.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeVar, cast

from langsmith import traceable
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import APIError
from app.models.llm_usage import LlmUsageEvent
from app.services.structured_llm import ChatTurn, generate_structured

T = TypeVar("T", bound=BaseModel)

LLMCallType = Literal["chat", "lesson_json", "report"]
UserLimitKind = Literal["chat", "lesson_start"]
UsageStatus = Literal["ok", "error"]

_LLM_CALL_TYPES = ("chat", "lesson_json", "report")
_MINUTE_SECONDS = 60
_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400


def _user_hash(user_id: uuid.UUID) -> str:
    """Stable, non-reversible id for filtering traces by learner."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]


def estimate_input_tokens(*parts: str) -> int:
    """Rough pre-flight input size: 4 characters per token."""
    return sum(len(part) for part in parts) // 4


def _retry_after(oldest: datetime | None, window_seconds: int) -> int:
    if oldest is None:
        return window_seconds
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - oldest).total_seconds()
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
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
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


async def check_and_record_user_limit(db: AsyncSession, user_id: uuid.UUID, *, kind: UserLimitKind) -> None:
    """Enforce the per-user chat hour or lesson-start day bucket.

    Chat is checked against Gemini `chat` rows (recorded by the following
    `reserve_llm_call`). A lesson start inserts one `lesson_start` row.
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

    count, _, oldest = await _window_stats(db, window_seconds=window, user_id=user_id, call_types=call_types)
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


async def reserve_llm_call(
    db: AsyncSession,
    user_id: uuid.UUID,
    call_type: LLMCallType,
    *,
    estimated_input_tokens: int,
) -> LlmUsageEvent:
    """Pre-flight global RPM, RPD, and input TPM, then insert `reserved`.

    TPM is the sum of `input_tokens` already in the rolling minute plus
    `estimated_input_tokens` for this prompt. Raises `429 LLM_RATE_LIMIT_EXCEEDED`
    with `Retry-After` (60s for RPM/TPM, remaining time in the 24h window for RPD).
    """
    now = datetime.now(UTC)
    minute_start = now - timedelta(seconds=_MINUTE_SECONDS)
    in_minute = LlmUsageEvent.created_at >= minute_start
    # One round trip for both windows.
    minute_count, minute_tokens, day_count, day_oldest = (
        await db.execute(
            select(
                func.count().filter(in_minute),
                func.coalesce(func.sum(LlmUsageEvent.input_tokens).filter(in_minute), 0),
                func.count(),
                func.min(LlmUsageEvent.created_at),
            ).where(
                LlmUsageEvent.created_at >= now - timedelta(seconds=_DAY_SECONDS),
                LlmUsageEvent.call_type.in_(_LLM_CALL_TYPES),
            )
        )
    ).one()
    if minute_count >= settings.llm_rpm_limit or minute_tokens + estimated_input_tokens > settings.llm_input_tpm_limit:
        raise _limit_error("LLM rate limit exceeded", "LLM_RATE_LIMIT_EXCEEDED", _MINUTE_SECONDS)
    if day_count >= settings.llm_rpd_limit:
        raise _limit_error("LLM rate limit exceeded", "LLM_RATE_LIMIT_EXCEEDED", _retry_after(day_oldest, _DAY_SECONDS))

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
    input_tokens: int | None,
    status: UsageStatus,
    model: str | None,
) -> None:
    """Mark a reserved call `ok` or `error`.

    A known input count is stored for both statuses. Pass None to keep the
    reserve estimate, which is only correct when usage never arrived.
    """
    async with _side_session(db) as side:
        row = await side.get(LlmUsageEvent, event.id)
        if row is None:
            return
        row.status = status
        row.model = model
        if input_tokens is not None:
            row.input_tokens = input_tokens
        await side.commit()
    event.status = status
    event.model = model
    if input_tokens is not None:
        event.input_tokens = input_tokens


def _trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """LangSmith trace inputs without the DB session or callbacks."""
    return {k: v for k, v in inputs.items() if k not in ("db", "before_call", "user_id")}


_F = TypeVar("_F", bound=Callable[..., Any])


def _traced(fn: _F) -> _F:
    """`@traceable` that keeps the wrapped signature for type checkers. No-op unless tracing is on."""
    return cast(_F, traceable(run_type="chain", name=fn.__name__, process_inputs=_trace_inputs)(fn))


@_traced
async def metered_structured_call(
    db: AsyncSession,
    user_id: uuid.UUID,
    call_type: LLMCallType,
    *,
    model_id: str,
    schema: type[T],
    system_instruction: str,
    history: list[ChatTurn],
    before_call: Callable[[], Awaitable[None]] | None = None,
    trace_metadata: Mapping[str, Any] | None = None,
) -> T:
    """Reserve one Gemini call, optionally run `before_call`, then parse a model.

    The reserve estimate is the character length of the system instruction and
    history divided by 4. A parsed model completes the row as `ok`. Any
    exception from the Gemini call completes it as `error`. Persistence of the
    model stays with the caller, so a later insert failure leaves the row `ok`.
    """
    event = await reserve_llm_call(
        db,
        user_id,
        call_type,
        estimated_input_tokens=estimate_input_tokens(system_instruction, *(turn.text for turn in history)),
    )
    if before_call is not None:
        await before_call()

    known_tokens: int | None = None

    async def on_usage(count: int) -> None:
        nonlocal known_tokens
        known_tokens = count

    try:
        parsed = await generate_structured(
            model_id=model_id,
            schema=schema,
            system_instruction=system_instruction,
            history=history,
            call_type=call_type,
            on_usage=on_usage,
            trace_metadata={"user_id_hash": _user_hash(user_id), **(trace_metadata or {})},
        )
    except Exception:
        await complete(db, event, input_tokens=known_tokens, status="error", model=model_id)
        raise
    await complete(db, event, input_tokens=known_tokens, status="ok", model=model_id)
    return parsed
