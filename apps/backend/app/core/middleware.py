"""HTTP middleware: request ID correlation + structured access logs."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# High-frequency paths that should not emit access logs.
_SKIP_ACCESS_LOG_PATHS = frozenset({"/metrics", "/api/v1/health"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach `request.state.request_id`, echo it on the response, log access lines."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "unhandled_exception",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "status_code": 500,
                },
            )
            raise

        response.headers[REQUEST_ID_HEADER] = request_id
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if request.url.path not in _SKIP_ACCESS_LOG_PATHS:
            level = logger.warning if response.status_code >= 400 else logger.info
            level(
                "http_request",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        return response


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)
