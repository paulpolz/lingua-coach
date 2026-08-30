"""Judge JSON contract: parse, normalize, and repair-prompt — no Gemini I/O.

A rubric change is a new version file (`lesson_turn_v2`). Never silently
compare v1 scores to v2.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

Score = Literal["pass", "fail"]

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
_PASS = frozenset({"pass", "true", "yes", "ok", "1"})
_FAIL = frozenset({"fail", "false", "no", "0"})


class JudgeVerdict(BaseModel):
    """Structured judge output. `rationale` may be per-dimension or one string."""

    scores: dict[str, Score]
    rationale: dict[str, str] | str = ""
    span: str | None = None
    rubric_version: str | None = None


class JudgeParseError(ValueError):
    """First-pass JSON/schema failure — caller may repair-once."""


def extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidates = [text]
    for match in _JSON_FENCE.findall(text):
        candidates.append(match.strip())
    # Object slice when the model wraps JSON in prose.
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if end > start:
            candidates.append(text[start : end + 1])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _normalize_score(value: Any) -> Score | None:
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in _PASS:
        return "pass"
    if token in _FAIL:
        return "fail"
    return None


def _normalize_rationale(value: Any) -> dict[str, str] | str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return str(value)


def parse_judge_verdict(
    raw: str,
    *,
    dimensions: tuple[str, ...],
    rubric_version: str,
) -> JudgeVerdict:
    """Parse model text into a verdict. Raises JudgeParseError on failure."""
    data = extract_json_object(raw)
    if data is None:
        raise JudgeParseError("judge output is not a JSON object")

    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise JudgeParseError("scores must be an object of dimension → pass|fail")

    scores: dict[str, Score] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for dim in dimensions:
        if dim not in raw_scores:
            missing.append(dim)
            continue
        normalized = _normalize_score(raw_scores[dim])
        if normalized is None:
            invalid.append(dim)
            continue
        scores[dim] = normalized
    if missing:
        raise JudgeParseError("missing score dimensions: " + ", ".join(missing))
    if invalid:
        raise JudgeParseError("invalid scores (need pass|fail): " + ", ".join(invalid))

    span = data.get("span")
    if span is not None:
        span = str(span) or None

    try:
        return JudgeVerdict(
            scores=scores,
            rationale=_normalize_rationale(data.get("rationale")),
            span=span,
            rubric_version=rubric_version,
        )
    except ValidationError as exc:
        raise JudgeParseError(str(exc).split("\n")[0][:240]) from exc


def build_repair_prompt(original_prompt: str, invalid_raw: str, error: Exception) -> str:
    """Same repair-once shape as lesson generation: error + previous + JSON only."""
    return (
        f"{original_prompt}\n\n---\nYour previous response could not be parsed as valid JSON, "
        f"or did not match the required judge schema.\n\nValidation error: {error}\n\n"
        f"Your previous response was:\n{invalid_raw}\n\n"
        "Respond again with ONLY a corrected JSON object matching the schema exactly — "
        "no markdown, no prose, no code fences. "
        'Required keys: "scores" (every listed dimension → "pass" or "fail"), '
        '"rationale" (object of short reasons, or one string), optional "span".'
    )


def verdict_to_dict(verdict: JudgeVerdict) -> dict[str, Any]:
    return verdict.model_dump()


class RubricSpec(BaseModel):
    version: str
    dimensions: tuple[str, ...]
    markdown_name: str
    title: str = ""

    model_config = ConfigDict(frozen=True)


class JudgeCallResult(BaseModel):
    """Informational judge record stored on a case result. Never gates CI."""

    rubric_version: str
    scores: dict[str, Score] | None = None
    rationale: dict[str, str] | str | None = None
    span: str | None = None
    source: Literal["live", "canned", "skipped"] = "skipped"
    repaired: bool = False
    skip_reason: str | None = None
    error: str | None = None
    self_consistency: dict[str, Any] | None = None
    trials: list[dict[str, Any]] | None = None

    def as_record(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        return data
