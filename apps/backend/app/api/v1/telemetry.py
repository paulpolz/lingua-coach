"""Lightweight client error ingestion for cross-stack debugging.

Frontend posts structured errors (no PII / no prompts). They land in the same
JSON stdout stream as backend logs and increment `client_errors_total`.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.core.errors import APIError
from app.core.logging import get_logger
from app.core.metrics import record_client_error
from app.core.middleware import get_request_id
from app.services.rate_limit import check_and_record

logger = get_logger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_CLIENT_ERROR_LIMIT_PER_HOUR = 120
Surface = Literal["onboarding", "lesson", "dashboard", "api", "unknown"]


class ClientErrorReport(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    surface: Surface = "unknown"
    request_id: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=256)
    meta: dict[str, Any] | None = None


@router.post("/client-errors", status_code=204)
async def report_client_error(payload: ClientErrorReport, request: Request) -> Response:
    client_host = request.client.host if request.client else "unknown"
    rate_key = f"client_errors:{client_host}"
    if not check_and_record(rate_key, _CLIENT_ERROR_LIMIT_PER_HOUR):
        raise APIError(
            status_code=429,
            detail="Client error reporting rate limit exceeded",
            code="RATE_LIMIT_EXCEEDED",
        )

    request_id = payload.request_id or get_request_id(request)
    # Drop oversized / unexpected meta keys — keep this payload small and non-sensitive.
    safe_meta: dict[str, Any] | None = None
    if payload.meta:
        safe_meta = {str(k)[:64]: str(v)[:200] for k, v in list(payload.meta.items())[:10]}

    record_client_error(code=payload.code, surface=payload.surface)
    logger.warning(
        "client_error",
        extra={
            "event": "client_error",
            "request_id": request_id,
            "code": payload.code,
            "surface": payload.surface,
            "path": payload.path,
            "client_message": payload.message,
            "meta": safe_meta,
        },
    )
    return Response(status_code=204)
