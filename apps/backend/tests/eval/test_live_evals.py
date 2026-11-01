"""Live LangSmith experiments against the real LLM. Excluded by default (`-m "not eval"`).

uv run pytest -m eval tests/eval
"""

from __future__ import annotations

import os

import pytest

from app.config import settings
from evals.run import run

pytestmark = pytest.mark.eval


@pytest.mark.skipif(
    not (os.environ.get("LANGSMITH_API_KEY") and os.environ.get("EVAL_LLM_API_KEY")),
    reason="needs LANGSMITH_API_KEY and an LLM API key in the environment",
)
@pytest.mark.parametrize("dataset", ["lesson_turns"])
async def test_dataset_scores_stay_above_threshold(dataset: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", os.environ["EVAL_LLM_API_KEY"])
    assert await run(dataset, prefix="pytest", min_score=0.8) == 0
