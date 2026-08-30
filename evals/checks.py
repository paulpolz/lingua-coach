"""Deterministic eval checks. Run before any LLM judge.

Unknown names are reported by `run_checks` with `unknown=True` so the runner
treats them as a case error (not inverted by `expect_fail`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.schemas.lesson import LessonCurriculum
from app.services import extraction
from app.services.languages import normalize_language

# Distinctive English explanation phrases — not a language-ID model.
_ENGLISH_PHRASES = (
    "this means",
    "that means",
    "which means",
    "in english",
    "in other words",
    "for example",
    "you should",
    "you need to",
    "try to",
    "don't worry",
    "do not worry",
    "let's",
    "the word",
    "the correct",
    "remember that",
    "this is called",
    "we say",
    "in spanish we",
)

# Whole-word function/explanation tokens that are rare as Spanish/French/etc.
# grammar in learner-facing tutor prose. Intentionally omits "a"/"to"/"in".
_ENGLISH_FUNCTION_WORDS = frozenset(
    {
        "the",
        "because",
        "however",
        "although",
        "should",
        "would",
        "your",
        "please",
        "cannot",
        "isn't",
        "aren't",
        "don't",
        "doesn't",
        "didn't",
        "that's",
        "there's",
        "here's",
        "they're",
        "we're",
        "you're",
    }
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
_WORD = re.compile(r"[A-Za-z']+")


@dataclass
class CheckContext:
    raw_completion: str
    locale_native: str | None
    locale_target: str | None
    fixture: dict[str, Any]
    mode: str
    case: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    unknown: bool = False


def run_checks(names: Sequence[str], ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in names:
        fn = CHECKS.get(name)
        if fn is None:
            results.append(
                CheckResult(
                    name=name,
                    passed=False,
                    detail=f"unknown check: {name}",
                    unknown=True,
                )
            )
            continue
        try:
            results.append(fn(ctx))
        except Exception as exc:  # noqa: BLE001 - check failures are data, not crashes
            results.append(CheckResult(name=name, passed=False, detail=f"check error: {exc}"))
    return results


def check_extract_lesson_turn(ctx: CheckContext) -> CheckResult:
    turn = extraction.extract_lesson_turn(ctx.raw_completion)
    if turn is None:
        return CheckResult("extract_lesson_turn", False, "no valid json:lesson_turn block")
    return CheckResult("extract_lesson_turn", True, "parsed")


def check_extract_learner_profile(ctx: CheckContext) -> CheckResult:
    profile = extraction.extract_learner_profile(ctx.raw_completion)
    if profile is None:
        return CheckResult("extract_learner_profile", False, "no valid json:learner_profile block")
    return CheckResult("extract_learner_profile", True, "parsed")


def check_extract_course_roadmap(ctx: CheckContext) -> CheckResult:
    roadmap = extraction.extract_course_roadmap(ctx.raw_completion)
    if roadmap is None:
        return CheckResult("extract_course_roadmap", False, "no valid json:course_roadmap block")
    return CheckResult("extract_course_roadmap", True, "parsed")


def _collect_string_values(value: Any, into: list[str]) -> None:
    if isinstance(value, str):
        into.append(value)
    elif isinstance(value, Mapping):
        for inner in value.values():
            _collect_string_values(inner, into)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            _collect_string_values(inner, into)


def learner_facing_prose(raw: str) -> str:
    """Conversational / learner-facing text with structured JSON keys removed.

    Chat completions: strip fenced `json:*` blocks. Bare JSON (lesson
    generation): parse and keep string *values* only so English keys are ignored.
    """
    stripped = extraction.strip_structured_blocks(raw)
    text = stripped.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return stripped
        values: list[str] = []
        _collect_string_values(data, values)
        return "\n".join(values)
    return stripped


def _target_is_english(target: str | None) -> bool:
    if not target or not str(target).strip():
        return False
    return normalize_language(str(target)) == "en"


def check_no_english_learner_facing(ctx: CheckContext) -> CheckResult:
    if _target_is_english(ctx.locale_target):
        return CheckResult(
            "no_english_learner_facing",
            True,
            "skipped: locale.target is English",
        )
    if not (ctx.locale_target or "").strip():
        return CheckResult(
            "no_english_learner_facing",
            True,
            "skipped: locale.target unset",
        )

    prose = learner_facing_prose(ctx.raw_completion)
    lowered = prose.lower()
    hits: list[str] = []
    for phrase in _ENGLISH_PHRASES:
        if phrase in lowered:
            hits.append(f"phrase:{phrase}")
    tokens = {m.group(0).lower() for m in _WORD.finditer(prose)}
    function_hits = sorted(tokens & _ENGLISH_FUNCTION_WORDS)
    if len(function_hits) >= 2:
        hits.append("words:" + ",".join(function_hits[:8]))
    elif len(function_hits) == 1 and not hits:
        # A single distinctive function word plus no phrases: still fail — "the"
        # in Spanish-immersion tutor prose is the usual L1 leak.
        hits.append("word:" + function_hits[0])

    if hits:
        return CheckResult(
            "no_english_learner_facing",
            False,
            "English learner-facing leak: " + "; ".join(hits[:5]),
        )
    return CheckResult("no_english_learner_facing", True, "no English explanation markers")


def check_roadmap_target_language_matches(ctx: CheckContext) -> CheckResult:
    roadmap = extraction.extract_course_roadmap(ctx.raw_completion)
    if roadmap is None:
        return CheckResult(
            "roadmap_target_language_matches",
            False,
            "no valid json:course_roadmap block",
        )
    expected = (ctx.locale_target or "").strip()
    if not expected:
        return CheckResult(
            "roadmap_target_language_matches",
            False,
            "case locale.target is missing",
        )
    actual = roadmap.summary.target_language
    if actual is None or not str(actual).strip():
        return CheckResult(
            "roadmap_target_language_matches",
            False,
            "roadmap.summary.target_language is missing",
        )
    if normalize_language(str(actual)) != normalize_language(expected):
        return CheckResult(
            "roadmap_target_language_matches",
            False,
            f"target_language {actual!r} != locale.target {expected!r}",
        )
    return CheckResult("roadmap_target_language_matches", True, f"target_language={actual}")


def check_pattern_type_articles(ctx: CheckContext) -> CheckResult:
    turn = extraction.extract_lesson_turn(ctx.raw_completion)
    if turn is None:
        return CheckResult("pattern_type_articles", False, "no valid json:lesson_turn block")
    labels: list[str] = [m.pattern_type for m in turn.mistakes]
    labels.extend(c.type for c in turn.corrections)
    if any("article" in (label or "").lower() for label in labels):
        return CheckResult("pattern_type_articles", True, "pattern_type contains articles")
    return CheckResult(
        "pattern_type_articles",
        False,
        "no mistake/correction pattern_type containing 'articles'",
    )


def parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidates = [text]
    for match in _JSON_FENCE.findall(text):
        candidates.append(match.strip())
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def curriculum_from_completion(raw: str) -> LessonCurriculum | None:
    data = parse_json_object(raw)
    if data is None:
        return None
    try:
        return LessonCurriculum.model_validate(data)
    except ValidationError:
        return None


def check_curriculum_valid(ctx: CheckContext) -> CheckResult:
    data = parse_json_object(ctx.raw_completion)
    if data is None:
        return CheckResult("curriculum_valid", False, "completion is not a JSON object")
    try:
        LessonCurriculum.model_validate(data)
    except ValidationError as exc:
        return CheckResult("curriculum_valid", False, str(exc).split("\n")[0][:240])
    return CheckResult("curriculum_valid", True, "LessonCurriculum validated")


def roadmap_from_fixture(fixture: Mapping[str, Any]) -> dict[str, Any] | None:
    for key in ("roadmap", "course_roadmap"):
        value = fixture.get(key)
        if isinstance(value, dict):
            return value
    gen = fixture.get("generation_context")
    plan = fixture.get("active_plan")
    if isinstance(gen, Mapping):
        plan = gen.get("active_plan") or plan
        nested = gen.get("roadmap")
        if isinstance(nested, dict):
            return nested
    if isinstance(plan, Mapping):
        roadmap = plan.get("roadmap")
        if isinstance(roadmap, dict):
            return roadmap
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _alignment_candidates(roadmap: Mapping[str, Any]) -> list[str]:
    """Theme grammar_focus (+ current-block summary). Avoid whole-milestone
    prose so common words cannot false-align a wrong focus."""
    out: list[str] = []
    block = roadmap.get("current_block") or {}
    if isinstance(block, Mapping):
        for theme in block.get("themes") or []:
            if isinstance(theme, Mapping) and theme.get("grammar_focus"):
                out.append(_norm(str(theme["grammar_focus"])))
        summary = block.get("focus_summary")
        if summary:
            out.append(_norm(str(summary)))
    if not out:
        for ms in roadmap.get("milestones") or []:
            if isinstance(ms, Mapping) and ms.get("skill_developed"):
                out.append(_norm(str(ms["skill_developed"])))
    return [c for c in out if c]


def check_grammar_focus_aligned(ctx: CheckContext) -> CheckResult:
    curriculum = curriculum_from_completion(ctx.raw_completion)
    if curriculum is None:
        return CheckResult("grammar_focus_aligned", False, "could not parse LessonCurriculum")
    roadmap = roadmap_from_fixture(ctx.fixture)
    if not roadmap:
        return CheckResult(
            "grammar_focus_aligned",
            False,
            "fixture has no roadmap / active_plan.roadmap",
        )
    focus = _norm(curriculum.grammar_focus)
    if not focus:
        return CheckResult("grammar_focus_aligned", False, "empty grammar_focus")
    candidates = _alignment_candidates(roadmap)
    if any(c in focus or focus in c for c in candidates):
        return CheckResult("grammar_focus_aligned", True, "grammar_focus matches fixture theme")
    return CheckResult(
        "grammar_focus_aligned",
        False,
        "grammar_focus not found in fixture roadmap/milestone themes",
    )


def check_exit_criteria_nonempty_unique(ctx: CheckContext) -> CheckResult:
    curriculum = curriculum_from_completion(ctx.raw_completion)
    if curriculum is None:
        return CheckResult(
            "exit_criteria_nonempty_unique", False, "could not parse LessonCurriculum"
        )
    stripped = [c.strip() for c in curriculum.exit_criteria]
    if not stripped:
        return CheckResult("exit_criteria_nonempty_unique", False, "exit_criteria is empty")
    if any(not item for item in stripped):
        return CheckResult("exit_criteria_nonempty_unique", False, "empty string in exit_criteria")
    lowered = [item.lower() for item in stripped]
    if len(lowered) != len(set(lowered)):
        return CheckResult("exit_criteria_nonempty_unique", False, "duplicate exit_criteria")
    return CheckResult("exit_criteria_nonempty_unique", True, f"{len(stripped)} unique criteria")


def _milestone_indices(roadmap: Mapping[str, Any]) -> set[int]:
    indices: set[int] = set()
    milestones = roadmap.get("milestones") or []
    for i, ms in enumerate(milestones):
        if isinstance(ms, Mapping) and ms.get("index") is not None:
            try:
                indices.add(int(ms["index"]))
            except (TypeError, ValueError):
                indices.add(i)
        else:
            indices.add(i)
    return indices


def check_invented_milestone(ctx: CheckContext) -> CheckResult:
    """Fail when generation `milestone_index` is not in the fixture roadmap."""
    curriculum = curriculum_from_completion(ctx.raw_completion)
    if curriculum is None:
        return CheckResult("invented_milestone", False, "could not parse LessonCurriculum")
    roadmap = roadmap_from_fixture(ctx.fixture)
    if not roadmap:
        return CheckResult("invented_milestone", False, "fixture has no roadmap to ground against")
    indices = _milestone_indices(roadmap)
    if not indices:
        return CheckResult("invented_milestone", False, "fixture roadmap has no milestones")
    if curriculum.milestone_index not in indices:
        return CheckResult(
            "invented_milestone",
            False,
            f"milestone_index {curriculum.milestone_index} not in fixture indices {sorted(indices)}",
        )
    return CheckResult(
        "invented_milestone",
        True,
        f"milestone_index {curriculum.milestone_index} is in the injected roadmap",
    )


def check_one_question_rule(ctx: CheckContext) -> CheckResult:
    prose = extraction.strip_structured_blocks(ctx.raw_completion)
    count = prose.count("?")
    if count > 1:
        return CheckResult(
            "one_question_rule",
            False,
            f"{count} '?' in learner-facing prose (max 1)",
        )
    return CheckResult("one_question_rule", True, f"{count} question mark(s)")


CHECKS: dict[str, Any] = {
    "extract_lesson_turn": check_extract_lesson_turn,
    "extract_learner_profile": check_extract_learner_profile,
    "extract_course_roadmap": check_extract_course_roadmap,
    "no_english_learner_facing": check_no_english_learner_facing,
    "roadmap_target_language_matches": check_roadmap_target_language_matches,
    "pattern_type_articles": check_pattern_type_articles,
    "curriculum_valid": check_curriculum_valid,
    "grammar_focus_aligned": check_grammar_focus_aligned,
    "exit_criteria_nonempty_unique": check_exit_criteria_nonempty_unique,
    "invented_milestone": check_invented_milestone,
    "one_question_rule": check_one_question_rule,
}
