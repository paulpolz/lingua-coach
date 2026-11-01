"""LLM schema behavior: normalization and stripping hold, unknown keys are ignored."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.llm import LessonReply, MistakeEntry


def test_mistake_pattern_labels_are_normalized() -> None:
    entry = MistakeEntry(pattern_type="  Missing   Articles ", example_text="x", correction="y")
    assert entry.pattern_type == "missing articles"


def test_blank_pattern_labels_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MistakeEntry(pattern_type="   ", example_text="x", correction="y")


def test_reply_content_is_stripped_and_unknown_keys_ignored() -> None:
    reply = LessonReply.model_validate({"content": "  hi ", "unknown": {"a": 1}})
    assert reply.content == "hi"
    assert "unknown" not in reply.model_dump()


def test_empty_content_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LessonReply(content="   ")
