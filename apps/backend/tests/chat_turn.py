"""Post one chat turn to the stream and read it back as the stored transcript row."""

from __future__ import annotations

import json
from typing import Any

import httpx


class TurnResult:
    """Enough of an HTTP response for the chat tests.

    A finished stream is the saved assistant row (`message_id`, `content`, `metadata`).
    An HTTP error before the body is that JSON body. An SSE `error` event keeps status 200
    and `json()` is the event payload.
    """

    def __init__(self, response: httpx.Response, body: dict[str, Any]) -> None:
        self.status_code = response.status_code
        self.headers = response.headers
        self.text = response.text
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


def parse_sse(body: str) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data += line.removeprefix("data:").strip()
        parsed.append((name, json.loads(data)))
    return parsed


async def post_turn(client: httpx.AsyncClient, messages_url: str, content: str) -> TurnResult:
    """POST `{messages_url}/stream`. `messages_url` is the GET transcript path."""
    response = await client.post(f"{messages_url}/stream", json={"content": content})
    if not response.headers.get("content-type", "").startswith("text/event-stream"):
        return TurnResult(response, response.json())
    events = parse_sse(response.text)
    if not events or events[-1][0] == "error":
        payload = events[-1][1] if events else {}
        return TurnResult(response, payload)
    message_id = events[-1][1]["message_id"]
    listed = await client.get(messages_url)
    stored = next(item for item in listed.json()["messages"] if item["id"] == message_id)
    return TurnResult(
        response,
        {"message_id": stored["id"], "content": stored["content"], "metadata": stored.get("metadata") or {}},
    )
