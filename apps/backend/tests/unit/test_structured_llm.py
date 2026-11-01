"""generate_structured against the fake chat model (ported from test_structured_output.py)."""

from __future__ import annotations

from app.schemas.llm import LessonCurriculum
from app.services.structured_llm import ChatTurn, generate_structured
from tests.fake_llm import RAW_INPUT_TOKENS, FakeLLM
from tests.samples import curriculum


async def test_parsed_curriculum_reports_raw_input_tokens(fake_llm: FakeLLM) -> None:
    parsed_in = curriculum()
    fake_llm.push(parsed_in)
    seen: list[int] = []

    async def on_usage(count: int) -> None:
        seen.append(count)

    parsed = await generate_structured(
        model_id="gemini-test",
        schema=LessonCurriculum,
        system_instruction="system",
        history=[ChatTurn(role="user", text="next lesson")],
        call_type="lesson_json",
        on_usage=on_usage,
    )

    assert parsed is parsed_in
    assert seen == [RAW_INPUT_TOKENS]
    assert fake_llm.init_kwargs[-1]["max_retries"] == 0
    call = fake_llm.calls[-1]
    assert call.schema is LessonCurriculum
    assert call.structured_kwargs["method"] == "json_schema"
    assert call.structured_kwargs["include_raw"] is True


async def test_trace_config_names_the_call_and_carries_metadata(fake_llm: FakeLLM) -> None:
    fake_llm.push(curriculum())

    await generate_structured(
        model_id="m",
        schema=LessonCurriculum,
        system_instruction="s",
        history=[ChatTurn(role="user", text="x")],
        call_type="lesson_json",
        trace_metadata={"lesson_number": 3},
    )

    config = fake_llm.calls[-1].config
    assert config is not None
    assert config["run_name"] == "lesson_json"
    assert "lesson_json" in config["tags"] and "env:local" in config["tags"]
    assert config["metadata"]["lesson_number"] == 3
    assert config["metadata"]["call_type"] == "lesson_json"
