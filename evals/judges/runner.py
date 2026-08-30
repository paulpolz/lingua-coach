"""Structured Gemini judge: fixed rubric prompt, JSON out, repair-once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.judges.lesson_generation_v1 import SPEC as LESSON_GENERATION_V1
from evals.judges.lesson_turn_v1 import SPEC as LESSON_TURN_V1
from evals.judges.onboarding_v1 import SPEC as ONBOARDING_V1
from evals.judges.schema import (
    JudgeCallResult,
    JudgeParseError,
    RubricSpec,
    _normalize_score,
    build_repair_prompt,
    parse_judge_verdict,
    verdict_to_dict,
)

JUDGES_DIR = Path(__file__).resolve().parent

RUBRICS: dict[str, RubricSpec] = {
    LESSON_TURN_V1.version: LESSON_TURN_V1,
    LESSON_GENERATION_V1.version: LESSON_GENERATION_V1,
    ONBOARDING_V1.version: ONBOARDING_V1,
}

# Run-level tag: the v1 generation. A new file is a new version; do not mix.
RUBRIC_GENERATION = "v1"

_SYSTEM_PREFIX = (
    "You are a strict evaluator for a language-tutor product. "
    "Score only the listed dimensions as pass or fail. "
    "Return a single JSON object. Do not coach the learner."
)


def resolve_rubric(name: str) -> RubricSpec:
    spec = RUBRICS.get(str(name).strip())
    if spec is None:
        known = ", ".join(sorted(RUBRICS))
        raise KeyError(f"unknown rubric {name!r} (known: {known})")
    return spec


def load_rubric_markdown(spec: RubricSpec) -> str:
    path = JUDGES_DIR / spec.markdown_name
    return path.read_text(encoding="utf-8")


def system_instruction(spec: RubricSpec) -> str:
    return f"{_SYSTEM_PREFIX}\n\n{load_rubric_markdown(spec)}"


def _compact_context(case: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    loc = case.get("locale") or {}
    profile = fixture.get("learner_profile") or fixture.get("profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    time_budget = fixture.get("time_budget") or profile.get("time_budget")
    roadmap = fixture.get("roadmap") or fixture.get("course_roadmap") or {}
    block = roadmap.get("current_block") if isinstance(roadmap, dict) else {}
    milestones = []
    if isinstance(roadmap, dict):
        for ms in roadmap.get("milestones") or []:
            if isinstance(ms, dict):
                milestones.append(
                    {
                        "index": ms.get("index"),
                        "title": ms.get("title"),
                        "skill_developed": ms.get("skill_developed"),
                    }
                )
    return {
        "mode": case.get("mode"),
        "locale": {"native": loc.get("native"), "target": loc.get("target")},
        "goal": fixture.get("goal_outcome") or profile.get("goal_outcome"),
        "level": fixture.get("target_level") or profile.get("target_level"),
        "time_budget": time_budget,
        "current_block": {
            "milestone_index": (block or {}).get("milestone_index")
            if isinstance(block, dict)
            else None,
            "focus_summary": (block or {}).get("focus_summary")
            if isinstance(block, dict)
            else None,
        },
        "milestone_titles": milestones[:8],
    }


def build_user_prompt(
    spec: RubricSpec,
    *,
    case: dict[str, Any],
    fixture: dict[str, Any],
    completion: str,
) -> str:
    inp = case.get("input") or {}
    payload = {
        "rubric_version": spec.version,
        "dimensions": list(spec.dimensions),
        "context": _compact_context(case, fixture),
        "user_message": inp.get("user_message"),
        "tutor_completion": completion,
    }
    return (
        "Score the tutor_completion on every listed dimension.\n"
        "Use only the rubric. Context is compact (languages, goal, level, plan snippet).\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def canned_judge_path(evals_root: Path, case_id: str) -> Path:
    return evals_root / "fixtures" / "replay" / f"{case_id}.judge.json"


def load_canned_judge(evals_root: Path, case_id: str) -> dict[str, Any] | None:
    path = canned_judge_path(evals_root, case_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _coerce_canned_rationale(value: Any) -> dict[str, str] | str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return str(value)


def canned_to_result(data: dict[str, Any], spec: RubricSpec) -> JudgeCallResult:
    """Never raise — a bad .judge.json must not fail a gated suite."""
    raw = json.dumps(data, ensure_ascii=False)
    try:
        verdict = parse_judge_verdict(
            raw, dimensions=spec.dimensions, rubric_version=spec.version
        )
        record = verdict_to_dict(verdict)
        return JudgeCallResult(
            rubric_version=spec.version,
            scores=record["scores"],
            rationale=record.get("rationale"),
            span=record.get("span"),
            source="canned",
        )
    except JudgeParseError:
        pass
    except Exception as exc:  # noqa: BLE001
        return JudgeCallResult(
            rubric_version=spec.version,
            source="canned",
            error=f"canned judge JSON failed: {type(exc).__name__}: {exc}",
        )

    raw_scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    scores = {
        str(key): normalized
        for key, value in raw_scores.items()
        if (normalized := _normalize_score(value)) is not None
    }
    try:
        return JudgeCallResult(
            rubric_version=str(data.get("rubric_version") or spec.version),
            scores=scores or None,
            rationale=_coerce_canned_rationale(data.get("rationale")),
            span=None if data.get("span") is None else str(data.get("span")),
            source="canned",
            error="canned judge JSON failed schema parse; scores passed through if present",
        )
    except Exception as exc:  # noqa: BLE001
        return JudgeCallResult(
            rubric_version=str(data.get("rubric_version") or spec.version),
            source="canned",
            error=f"canned judge JSON failed schema parse: {type(exc).__name__}: {exc}",
        )


async def judge_once(
    spec: RubricSpec,
    *,
    case: dict[str, Any],
    fixture: dict[str, Any],
    completion: str,
    generate_json,
    ChatTurn,
) -> JudgeCallResult:
    """One Gemini JSON call + at most one schema repair. Never raises to gate CI."""
    from app.services.gemini import GeminiError

    system = system_instruction(spec)
    user_prompt = build_user_prompt(
        spec, case=case, fixture=fixture, completion=completion
    )
    repaired = False
    try:
        raw = await generate_json(
            system_instruction=system,
            history=[ChatTurn(role="user", text=user_prompt)],
        )
    except GeminiError as exc:
        return JudgeCallResult(
            rubric_version=spec.version,
            source="live",
            error=f"GeminiError {exc.code}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return JudgeCallResult(
            rubric_version=spec.version,
            source="live",
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        verdict = parse_judge_verdict(
            raw, dimensions=spec.dimensions, rubric_version=spec.version
        )
    except JudgeParseError as exc:
        repaired = True
        repair_prompt = build_repair_prompt(user_prompt, raw, exc)
        try:
            raw_retry = await generate_json(
                system_instruction=system,
                history=[ChatTurn(role="user", text=repair_prompt)],
            )
            verdict = parse_judge_verdict(
                raw_retry, dimensions=spec.dimensions, rubric_version=spec.version
            )
        except JudgeParseError as exc2:
            return JudgeCallResult(
                rubric_version=spec.version,
                source="live",
                repaired=True,
                error=f"judge schema failed after one repair: {exc2}",
            )
        except GeminiError as exc2:
            return JudgeCallResult(
                rubric_version=spec.version,
                source="live",
                repaired=True,
                error=f"GeminiError on repair {exc2.code}: {exc2}",
            )
        except Exception as exc2:  # noqa: BLE001
            return JudgeCallResult(
                rubric_version=spec.version,
                source="live",
                repaired=True,
                error=f"{type(exc2).__name__} on repair: {exc2}",
            )

    record = verdict_to_dict(verdict)
    return JudgeCallResult(
        rubric_version=spec.version,
        scores=record["scores"],
        rationale=record.get("rationale"),
        span=record.get("span"),
        source="live",
        repaired=repaired,
    )


def flipped_dimensions(
    trials: list[dict[str, Any]], dimensions: tuple[str, ...]
) -> list[str]:
    flips: list[str] = []
    for dim in dimensions:
        values = []
        for trial in trials:
            scores = trial.get("scores") or {}
            if dim in scores:
                values.append(scores[dim])
        if len(set(values)) > 1:
            flips.append(dim)
    return flips


async def judge_with_optional_repeats(
    spec: RubricSpec,
    *,
    case: dict[str, Any],
    fixture: dict[str, Any],
    completion: str,
    generate_json,
    ChatTurn,
    repeats: int = 1,
) -> JudgeCallResult:
    """`repeats` ≥ 2 is self-consistency (live only). First trial is the score."""
    n = max(1, int(repeats))
    first = await judge_once(
        spec,
        case=case,
        fixture=fixture,
        completion=completion,
        generate_json=generate_json,
        ChatTurn=ChatTurn,
    )
    if n == 1 or first.scores is None:
        return first

    trials = [first.as_record()]
    for _ in range(n - 1):
        extra = await judge_once(
            spec,
            case=case,
            fixture=fixture,
            completion=completion,
            generate_json=generate_json,
            ChatTurn=ChatTurn,
        )
        trials.append(extra.as_record())

    flips = flipped_dimensions(trials, spec.dimensions)
    first.self_consistency = {
        "n": n,
        "flips": flips,
        "stable": not flips,
    }
    first.trials = trials
    return first
