"""LLM schema behavior: stripping holds, unknown keys are ignored."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.llm import LessonReply


def test_reply_content_is_stripped_and_unknown_keys_ignored() -> None:
    reply = LessonReply.model_validate({"content": "  hi ", "unknown": {"a": 1}})
    assert reply.content == "hi"
    assert "unknown" not in reply.model_dump()


def test_empty_content_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LessonReply(content="   ")
