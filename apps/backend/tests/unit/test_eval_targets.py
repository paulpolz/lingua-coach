"""Eval targets build production prompts from the seed datasets (fake LLM, no network)."""

from __future__ import annotations

import pytest

from app.schemas.llm import LessonReply, OnboardingReply, ReportOp, ReportPatch
from evals.evaluators import EVALUATORS
from evals.run import load_examples
from evals.targets import TARGETS
from tests.fake_llm import FakeLLM
from tests.samples import curriculum

REPLIES = {
    "onboarding_turns": lambda: OnboardingReply(content="What is your native language?"),
    "lesson_turns": lambda: LessonReply(content="Good, and what is the next step with the client?"),
    "curriculum_gen": curriculum,
    "report_patch": lambda: ReportPatch(
        ops=[ReportOp(report_type="progress", op="append_entry", section_id="update_log", markdown="- ok")]
    ),
}


@pytest.mark.parametrize("dataset", sorted(TARGETS))
async def test_every_seed_example_runs_through_its_target_and_evaluators(dataset: str, fake_llm: FakeLLM) -> None:
    examples = load_examples(dataset)
    assert len(examples) >= 3
    for example in examples:
        fake_llm.push(REPLIES[dataset]())
        outputs = await TARGETS[dataset](example["inputs"])
        assert outputs["error"] is None
        for evaluator in EVALUATORS[dataset]:
            result = evaluator(example["inputs"], outputs, example.get("outputs", {}))
            assert result["score"] is None or 0.0 <= result["score"] <= 1.0


async def test_lesson_target_sends_the_time_line(fake_llm: FakeLLM) -> None:
    fake_llm.push(REPLIES["lesson_turns"]())
    await TARGETS["lesson_turns"](load_examples("lesson_turns")[0]["inputs"])
    assert "Time: 6 of 15 min used." in fake_llm.calls[-1].text
