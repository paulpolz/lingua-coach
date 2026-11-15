"""Agent runs return the existing schemas and meter one row per call."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.llm import LessonCurriculum, LessonReply, OnboardingReply, ReportPatch
from app.services.agents.curriculum import curriculum_agent
from app.services.agents.factory import _cached_model
from app.services.agents.lesson_chat import lesson_agent
from app.services.agents.onboarding import onboarding_agent
from app.services.agents.report import report_agent
from app.services.agents.runner import LLMError, metered_agent_run
from app.services.agents.tools import AgentContext, language_policy_tool
from tests.factories import make_lesson, make_profile, make_user
from tests.fake_llm import RAW_INPUT_TOKENS, FakeLLM, SchemaMismatch, ToolRound
from tests.integration.test_llm_usage_limits import _events
from tests.samples import curriculum


async def test_each_agent_returns_its_schema_and_reserves_once(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user)
    shared = {"user_id": user.id, "db": db}
    cases: list[tuple[object, str, object, AgentContext]] = [
        (
            onboarding_agent(None),
            "chat",
            OnboardingReply(content="What is your native language?"),
            AgentContext(**shared, call_type="chat", onboarding=True),  # type: ignore[arg-type]
        ),
        (
            lesson_agent(None),
            "chat",
            LessonReply(content="Try the order again."),
            AgentContext(**shared, call_type="chat", onboarding=False),  # type: ignore[arg-type]
        ),
        (
            curriculum_agent(),
            "lesson_json",
            curriculum(),
            AgentContext(**shared, call_type="lesson_json", lesson_number=2),  # type: ignore[arg-type]
        ),
        (
            report_agent(),
            "report",
            ReportPatch(ops=[]),
            AgentContext(**shared, call_type="report", lesson_id=lesson.id),  # type: ignore[arg-type]
        ),
    ]

    for agent, call_type, reply, context in cases:
        if call_type != "chat":
            assert agent.graph.checkpointer is None  # type: ignore[attr-defined]
        fake_llm.push(reply)  # type: ignore[arg-type]
        parsed: BaseModel = await metered_agent_run(
            db,
            user.id,
            call_type,  # type: ignore[arg-type]
            agent=agent,  # type: ignore[arg-type]
            user_text="go",
            context=context,
        )
        assert type(parsed) is type(reply)
        assert parsed == reply

    events = await _events(db)
    assert [event.call_type for event in events] == ["chat", "chat", "lesson_json", "report"]
    assert [event.status for event in events] == ["ok", "ok", "ok", "ok"]
    assert [event.input_tokens for event in events] == [RAW_INPUT_TOKENS] * 4
    assert "astream" not in fake_llm.modes


async def test_a_tool_round_sums_completed_messages_onto_one_row(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    fake_llm.push(ToolRound(reply=curriculum(), tool_name=language_policy_tool.name, text="draft"))

    parsed = await metered_agent_run(
        db,
        user.id,
        "lesson_json",
        agent=curriculum_agent(),
        user_text="next lesson",
        context=AgentContext(user_id=user.id, db=db, call_type="lesson_json", lesson_number=1),
    )

    assert isinstance(parsed, LessonCurriculum)
    events = await _events(db)
    assert len(events) == 1
    assert events[0].status == "ok"
    assert events[0].input_tokens == RAW_INPUT_TOKENS * 2


async def test_schema_error_keeps_the_reserve_estimate(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    fake_llm.input_tokens = 9999
    fake_llm.push(SchemaMismatch())

    with pytest.raises(LLMError) as caught:
        await metered_agent_run(
            db,
            user.id,
            "lesson_json",
            agent=curriculum_agent(),
            user_text="next lesson",
            context=AgentContext(user_id=user.id, db=db, call_type="lesson_json", lesson_number=1),
        )

    assert caught.value.code == "LLM_SCHEMA_ERROR"
    events = await _events(db)
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].input_tokens != 9999
    assert events[0].input_tokens > 0


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError("slow"), "LLM_TIMEOUT"),
        (RuntimeError("RESOURCE_EXHAUSTED today"), "LLM_QUOTA_EXCEEDED"),
        (RuntimeError("provider down"), "LLM_API_ERROR"),
        (LLMError("missing key", code="LLM_CONFIG_ERROR"), "LLM_CONFIG_ERROR"),
    ],
)
async def test_provider_failures_keep_their_codes(
    db: AsyncSession, fake_llm: FakeLLM, failure: Exception, code: str
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    fake_llm.push(failure)

    with pytest.raises(LLMError) as caught:
        await metered_agent_run(
            db,
            user.id,
            "lesson_json",
            agent=curriculum_agent(),
            user_text="next lesson",
            context=AgentContext(user_id=user.id, db=db, call_type="lesson_json"),
        )

    assert caught.value.code == code
    assert (await _events(db))[0].status == "error"


async def test_missing_api_key_raises_before_any_provider_call(
    fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "")
    _cached_model.cache_clear()

    with pytest.raises(LLMError) as caught:
        curriculum_agent()

    assert caught.value.code == "LLM_CONFIG_ERROR"
    assert fake_llm.init_kwargs == []
    assert fake_llm.calls == []


async def test_factory_uses_init_chat_model_without_retries_or_a_second_timeout(
    db: AsyncSession, fake_llm: FakeLLM
) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    fake_llm.push(curriculum())
    agent = curriculum_agent()
    seen: dict[str, object] = {}
    invoke = agent.graph.ainvoke

    async def _capture(inputs: object, config: dict | None = None, **kwargs: object) -> object:
        seen["config"] = config
        return await invoke(inputs, config, **kwargs)

    agent.graph.ainvoke = _capture

    await metered_agent_run(
        db,
        user.id,
        "lesson_json",
        agent=agent,
        user_text="next lesson",
        context=AgentContext(user_id=user.id, db=db, call_type="lesson_json", lesson_number=3),
        trace_metadata={"lesson_number": 3},
    )

    built = fake_llm.init_kwargs[-1]
    assert built["max_retries"] == 0
    assert "timeout" not in built
    assert str(built["model"]).startswith("google_genai:")
    passed = seen["config"]
    assert isinstance(passed, dict)
    assert passed["run_name"] == "lesson_json"
    assert passed["recursion_limit"] == 15
    assert "lesson_json" in passed["tags"] and "env:local" in passed["tags"]
    assert passed["metadata"]["lesson_number"] == 3
    assert passed["metadata"]["call_type"] == "lesson_json"
    assert passed["metadata"]["model"] == agent.model_id
    assert len(passed["metadata"]["user_id_hash"]) == 16
    assert str(user.id) not in str(passed["metadata"])
    call = fake_llm.calls[-1]
    assert call.schema is LessonCurriculum
    assert call.structured_kwargs["response_format"]["type"] == "json_schema"
    assert call.structured_kwargs["response_format"]["json_schema"]["name"] == "LessonCurriculum"
    assert call.config is not None
    assert "lesson_json" in call.config["tags"] and "env:local" in call.config["tags"]
    assert call.config["metadata"]["call_type"] == "lesson_json"
    assert call.config["metadata"]["user_id_hash"] == passed["metadata"]["user_id_hash"]
    assert fake_llm.modes == ["ainvoke"]
