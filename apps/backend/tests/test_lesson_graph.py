"""Lesson graph: replay skips the model; a second invalid completion fails."""

import copy
import json

import pytest

from app.services.gemini import GeminiError
from app.services.lesson_graph import LessonGenerationError, invoke_lesson_graph
from tests.fixtures import VALID_LESSON_CURRICULUM


@pytest.mark.asyncio
async def test_replay_skips_generate_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_kwargs):
        raise AssertionError("generate_json should not run for replay")

    monkeypatch.setattr("app.services.gemini.generate_json", boom)
    state = await invoke_lesson_graph(
        prompt="prompt",
        system_instruction="system",
        replay_completions=[json.dumps(VALID_LESSON_CURRICULUM)],
    )
    assert state["curriculum"] is not None
    assert state["curriculum"].lesson_goal == VALID_LESSON_CURRICULUM["lesson_goal"]


@pytest.mark.asyncio
async def test_replay_repair_uses_second_completion_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**_kwargs):
        raise AssertionError("generate_json should not run for replay")

    monkeypatch.setattr("app.services.gemini.generate_json", boom)
    state = await invoke_lesson_graph(
        prompt="prompt",
        system_instruction="system",
        replay_completions=["not json", json.dumps(VALID_LESSON_CURRICULUM)],
    )
    assert state["completions"] == ["not json", json.dumps(VALID_LESSON_CURRICULUM)]
    assert state["curriculum"].lesson_goal == VALID_LESSON_CURRICULUM["lesson_goal"]


@pytest.mark.asyncio
async def test_second_invalid_completion_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake(**_kwargs):
        calls["n"] += 1
        return "not json"

    monkeypatch.setattr("app.services.gemini.generate_json", fake)
    with pytest.raises(LessonGenerationError) as exc:
        await invoke_lesson_graph(prompt="prompt", system_instruction="system")
    assert calls["n"] == 2
    assert exc.value.completions == ["not json", "not json"]


@pytest.mark.asyncio
async def test_gemini_error_does_not_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake(**_kwargs):
        calls["n"] += 1
        raise GeminiError("simulated Gemini timeout", code="LLM_TIMEOUT", error_type="timeout")

    monkeypatch.setattr("app.services.gemini.generate_json", fake)
    with pytest.raises(GeminiError, match="simulated Gemini timeout"):
        await invoke_lesson_graph(prompt="prompt", system_instruction="system")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_replay_strips_listening_resource_and_remaps_speaking_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**_kwargs):
        raise AssertionError("generate_json should not run for replay")

    monkeypatch.setattr("app.services.gemini.generate_json", boom)
    raw = copy.deepcopy(VALID_LESSON_CURRICULUM)
    raw["input_task"] = {
        "type": "listening",
        "topic": "Hotel",
        "focus": "Articles",
        "resource": {
            "id": "invented",
            "kind": "audio",
            "title": "Clip",
            "url": "https://example.com/clip",
            "duration_sec": 60,
            "source": "x",
            "captions": "none",
            "synopsis": "x",
            "notice_points": ["a"],
        },
    }
    raw["slots"] = [
        {"id": "warmup", "label": "Warm", "exercise_set": "One"},
        {"id": "speaking", "label": "Oral", "exercise_set": "Talk"},
    ]
    state = await invoke_lesson_graph(
        prompt="prompt",
        system_instruction="system",
        replay_completions=[json.dumps(raw)],
    )
    curriculum = state["curriculum"]
    assert curriculum is not None
    assert curriculum.input_task.type == "reading"
    assert "resource" not in curriculum.input_task.model_dump()
    assert [slot.id for slot in curriculum.slots] == ["warmup", "writing"]
