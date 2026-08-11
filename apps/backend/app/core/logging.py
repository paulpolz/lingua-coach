"""Structured JSON logging to stdout for local Loki and Railway log search."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.config import settings

_CONFIGURED = False


class _LinguaJsonFormatter(JsonFormatter):
    """Emit timestamp, level, message, plus any `extra` fields as top-level JSON keys."""

    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_data, record, message_dict)
        log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        log_data["level"] = record.levelname
        if "message" not in log_data:
            log_data["message"] = record.getMessage()


def setup_logging() -> None:
    """Configure root logger once. Safe to call from app startup and tests."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _LinguaJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s",
            rename_fields={"name": "logger"},
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libraries unless debugging.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
