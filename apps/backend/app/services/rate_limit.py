"""In-process, per-key sliding-window rate limiting — no Redis (MVP per
docs/tech_requirements/backend.md NFRs). State resets on process restart;
acceptable for local MVP.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

_DEFAULT_WINDOW_SECONDS = 3600.0
_hits: dict[str, deque[float]] = defaultdict(deque)


def check_and_record(key: str, limit: int, *, window_seconds: float = _DEFAULT_WINDOW_SECONDS) -> bool:
    """Record a hit for `key` and return whether it's within `limit` for the
    trailing `window_seconds` (default one hour, e.g. `CHAT_RATE_LIMIT_PER_HOUR`;
    pass `window_seconds=86400` for `LESSON_START_RATE_LIMIT_PER_DAY`).

    Returns `False` (and does *not* record the hit) once the caller has hit
    the limit within the trailing window.
    """
    now = time.monotonic()
    window = _hits[key]
    while window and now - window[0] > window_seconds:
        window.popleft()
    if len(window) >= limit:
        return False
    window.append(now)
    return True


def reset() -> None:
    """Test helper — clear all recorded hits."""
    _hits.clear()
