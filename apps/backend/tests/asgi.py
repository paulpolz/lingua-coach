"""A raw ASGI call that reports the moment the response is fully sent.

httpx's ASGITransport only returns after background tasks finish, so it cannot show
that a response went out *before* a background task started.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.deps import get_current_principal
from app.db.session import get_db
from app.main import app
from tests.conftest import Auth


async def asgi_post(
    path: str,
    db_conn: AsyncConnection,
    auth: Auth,
    *,
    on_response: Callable[[str], None],
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        session = AsyncSession(
            bind=db_conn, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_principal] = lambda: auth.principal
    raw = json.dumps(body or {}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test"), (b"content-type", b"application/json")],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    delivered = False
    finished = asyncio.Event()
    status = 0
    chunks: list[bytes] = []

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await finished.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                on_response("response_sent")

    try:
        await app(scope, receive, send)
    finally:
        finished.set()
        app.dependency_overrides.clear()
    return status, json.loads(b"".join(chunks) or b"null")
