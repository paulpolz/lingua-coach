"""Common API error shape per docs/implementation-readiness.md §6.

`{ "detail": "Human-readable message", "code": "MACHINE_READABLE_CODE" }`
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status_code: int, detail: str, code: str, **extra: object) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        # Extra body fields for endpoints that need more than detail/code —
        # e.g. `409 ACTIVE_LESSON_EXISTS`'s `active_lesson_id` (readiness §6).
        self.extra = extra
        super().__init__(detail)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    content = {"detail": exc.detail, "code": exc.code, **exc.extra}
    return JSONResponse(status_code=exc.status_code, content=content)
