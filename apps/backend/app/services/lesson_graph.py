"""Lesson-generation branch: generate, validate, repair once.

The production job and the eval target both invoke this graph. Nodes call
`gemini.generate_json` without `response_schema`: `LessonCurriculum.partner_session`
is an open object Gemini's structured-output dialect rejects, so validation
stays JSON text, Pydantic, and one repair. A `replay_completions` list on the
state skips the model calls and feeds the frozen strings through validate.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.metrics import record_llm_retry
from app.schemas.lesson import LessonCurriculum
from app.services import gemini
from app.services.gemini import ChatTurn, GeminiError
from app.services.llm_usage import complete, estimate_input_tokens, reserve_gemini_call

logger = logging.getLogger(__name__)


class LessonGenerationError(RuntimeError):
    """Raised when the model fails to produce a valid curriculum after the
    one allowed repair retry."""

    def __init__(self, message: str, *, completions: list[str] | None = None) -> None:
        super().__init__(message)
        self.completions = list(completions or [])


class LessonGraphState(TypedDict, total=False):
    system_instruction: str
    prompt: str
    replay_completions: list[str]
    replay_index: int
    raw: str
    completions: list[str]
    curriculum: LessonCurriculum | None
    validation_error: str | None
    repair_attempted: bool
    job_id: str | None
    lesson_id: str | None


def _normalize_curriculum(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    raw_task = out.get("input_task")
    if isinstance(raw_task, dict):
        input_task = dict(raw_task)
        if input_task.get("type") == "listening":
            input_task["type"] = "reading"
        input_task.pop("resource", None)
        out["input_task"] = input_task

    slots = out.get("slots")
    if isinstance(slots, list):
        remapped: list[Any] = []
        seen_writing = any(
            isinstance(slot, dict) and slot.get("id") == "writing" for slot in slots
        )
        for slot in slots:
            if not isinstance(slot, dict):
                remapped.append(slot)
                continue
            if slot.get("id") == "speaking":
                if seen_writing:
                    continue
                slot = {**slot, "id": "writing"}
                seen_writing = True
            remapped.append(slot)
        out["slots"] = remapped
    return out


def _parse_curriculum(raw: str) -> LessonCurriculum:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = _normalize_curriculum(data)
    return LessonCurriculum.model_validate(data)


def _build_repair_prompt(original_prompt: str, invalid_raw: str, error: object) -> str:
    return (
        f"{original_prompt}\n\n---\nYour previous response could not be parsed as valid JSON, or did "
        f"not match the required schema.\n\nValidation error: {error}\n\nYour previous response was:\n"
        f"{invalid_raw}\n\nRespond again with ONLY a corrected JSON object matching the required "
        "schema exactly — no markdown, no prose, no code fences."
    )


async def _call_lesson_model(
    db: AsyncSession, user_id: uuid.UUID, *, system_instruction: str, prompt: str
) -> str:
    event = await reserve_gemini_call(
        db,
        user_id,
        "lesson_json",
        estimated_input_tokens=estimate_input_tokens(system_instruction, prompt),
    )
    tokens = event.input_tokens

    async def on_usage(prompt_token_count: int) -> None:
        nonlocal tokens
        tokens = prompt_token_count

    try:
        raw = await gemini.generate_json(
            system_instruction=system_instruction,
            history=[ChatTurn(role="user", text=prompt)],
            on_usage=on_usage,
        )
    except GeminiError:
        await complete(
            db,
            event,
            input_tokens=event.input_tokens,
            status="error",
            model=settings.gemini_model_lesson,
        )
        raise
    await complete(
        db,
        event,
        input_tokens=tokens,
        status="ok",
        model=settings.gemini_model_lesson,
    )
    return raw


async def _generate_raw(config: RunnableConfig, *, system_instruction: str, prompt: str) -> str:
    configurable = config.get("configurable") or {}
    db = configurable.get("db")
    user_id = configurable.get("user_id")
    if db is None or user_id is None:
        return await gemini.generate_json(
            system_instruction=system_instruction,
            history=[ChatTurn(role="user", text=prompt)],
        )
    return await _call_lesson_model(
        db, user_id, system_instruction=system_instruction, prompt=prompt
    )


async def _generate(state: LessonGraphState, config: RunnableConfig) -> dict[str, Any]:
    replay = list(state.get("replay_completions") or [])
    if replay:
        raw = replay[0]
        return {
            "raw": raw,
            "completions": [raw],
            "replay_index": 1,
            "curriculum": None,
            "repair_attempted": False,
        }
    raw = await _generate_raw(
        config,
        system_instruction=state["system_instruction"],
        prompt=state["prompt"],
    )
    return {
        "raw": raw,
        "completions": [raw],
        "replay_index": 0,
        "curriculum": None,
        "repair_attempted": False,
    }


def _validate(state: LessonGraphState) -> dict[str, Any]:
    try:
        curriculum = _parse_curriculum(state.get("raw") or "")
    except (json.JSONDecodeError, ValidationError) as exc:
        return {"curriculum": None, "validation_error": str(exc)}
    return {"curriculum": curriculum, "validation_error": None}


def _route(state: LessonGraphState) -> str:
    if state.get("curriculum") is not None or state.get("repair_attempted"):
        return "done"
    return "repair"


async def _repair(state: LessonGraphState, config: RunnableConfig) -> dict[str, Any]:
    replay = list(state.get("replay_completions") or [])
    index = int(state.get("replay_index") or 0)
    if replay:
        if index < len(replay):
            raw = replay[index]
            completions = list(state.get("completions") or [])
            completions.append(raw)
            return {
                "raw": raw,
                "completions": completions,
                "replay_index": index + 1,
                "repair_attempted": True,
                "curriculum": None,
            }
        return {"repair_attempted": True}

    record_llm_retry(call_type="lesson_json", reason="schema_repair")
    logger.info(
        "lesson_curriculum_schema_repair",
        extra={
            "event": "llm_retry",
            "reason": "schema_repair",
            "job_id": state.get("job_id"),
            "lesson_id": state.get("lesson_id"),
            "request_id": state.get("job_id"),
        },
    )
    repair_prompt = _build_repair_prompt(
        state["prompt"], state.get("raw") or "", state.get("validation_error") or ""
    )
    raw = await _generate_raw(
        config,
        system_instruction=state["system_instruction"],
        prompt=repair_prompt,
    )
    completions = list(state.get("completions") or [])
    completions.append(raw)
    return {"raw": raw, "completions": completions, "repair_attempted": True, "curriculum": None}


def _build_graph():
    graph = StateGraph(LessonGraphState)
    graph.add_node("generate", _generate)
    graph.add_node("validate", _validate)
    graph.add_node("repair", _repair)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", _route, {"done": END, "repair": "repair"})
    graph.add_edge("repair", "validate")
    return graph.compile()


_COMPILED = None


def _compiled_graph():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _build_graph()
    return _COMPILED


async def invoke_lesson_graph(
    *,
    prompt: str,
    system_instruction: str,
    db: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    lesson_id: uuid.UUID | None = None,
    replay_completions: list[str] | None = None,
) -> LessonGraphState:
    """Run generate → validate → one repair.

    `replay_completions` skips the model nodes. Without it, a second validation
    failure raises `LessonGenerationError`. `GeminiError` propagates immediately.
    """
    state = await _compiled_graph().ainvoke(
        {
            "system_instruction": system_instruction,
            "prompt": prompt,
            "replay_completions": list(replay_completions or []),
            "replay_index": 0,
            "completions": [],
            "repair_attempted": False,
            "job_id": str(job_id) if job_id else None,
            "lesson_id": str(lesson_id) if lesson_id else None,
        },
        config={"configurable": {"db": db, "user_id": user_id}},
    )
    if state.get("curriculum") is None and not replay_completions:
        raise LessonGenerationError(
            "Lesson curriculum failed schema validation after one repair retry: "
            f"{state.get('validation_error')}",
            completions=list(state.get("completions") or []),
        )
    return state
