"""Common API error shape per docs/implementation-readiness.md §6.

`{ "detail": "Human-readable message", "code": "MACHINE_READABLE_CODE" }`
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.middleware import REQUEST_ID_HEADER, get_request_id

logger = get_logger(__name__)


class APIError(Exception):
    def __init__(self, status_code: int, detail: str, code: str, **extra: object) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        # Extra body fields for endpoints that need more than detail/code —
        # e.g. `409 ACTIVE_LESSON_EXISTS`'s `active_lesson_id` (readiness §6).
        self.extra = extra
        super().__init__(detail)


def _with_request_id(request: Request, response: JSONResponse) -> JSONResponse:
    request_id = get_request_id(request)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    content = {"detail": exc.detail, "code": exc.code, **exc.extra}
    if exc.status_code >= 500:
        logger.error(
            "api_error",
            extra={
                "event": "api_error",
                "request_id": get_request_id(request),
                "path": request.url.path,
                "method": request.method,
                "status_code": exc.status_code,
                "code": exc.code,
            },
        )
    response = JSONResponse(status_code=exc.status_code, content=content)
    return _with_request_id(request, response)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map unexpected exceptions to the standard `{detail, code}` shape and log the stack."""
    logger.exception(
        "unhandled_exception",
        extra={
            "event": "unhandled_exception",
            "request_id": get_request_id(request),
            "path": request.url.path,
            "method": request.method,
            "error_type": type(exc).__name__,
        },
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )
    return _with_request_id(request, response)
