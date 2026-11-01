"""Snapshots of the HTTP contract and of every LLM JSON schema.

A diff here means the API or the prompt contract changed. If that was intended, refresh
with `UPDATE_SNAPSHOTS=1 uv run pytest tests/contract` and review the JSON diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.main import app
from app.schemas import llm

SNAPSHOTS = Path(__file__).parent / "snapshots"
LLM_SCHEMAS: list[type[BaseModel]] = [
    llm.OnboardingReply,
    llm.LessonReply,
    llm.LessonCurriculum,
    llm.ReportPatch,
    llm.CourseRoadmap,
]


def _check(name: str, data: dict[str, Any]) -> None:
    path = SNAPSHOTS / f"{name}.json"
    rendered = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.write_text(rendered, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == rendered, f"{name} contract changed; see module docstring"


def test_openapi_contract_matches_snapshot() -> None:
    _check("openapi", app.openapi())


@pytest.mark.parametrize("schema", LLM_SCHEMAS, ids=lambda s: s.__name__)
def test_llm_schema_matches_snapshot(schema: type[BaseModel]) -> None:
    _check(f"llm_{schema.__name__}", schema.model_json_schema())
