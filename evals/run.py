"""Offline eval entry point. Loads YAML cases and calls LangSmith `aevaluate`.

From repo root:

    PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay

`upload_results=False` unless `--upload` is set. Cases stay in the YAML files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any, Literal

import requests
from langsmith import Client
from langsmith.schemas import Example, LangSmithInfo

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency hint
    raise SystemExit(
        "PyYAML is required. Install backend dev extras: "
        "`cd apps/backend && uv sync --extra dev`"
    ) from exc

EVALS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVALS_ROOT.parent

if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))

try:
    from app.services.gemini import ChatTurn, GeminiError, generate_json, stream_chat
    from app.services.lesson_graph import LessonGenerationError, invoke_lesson_graph
    from app.services.prompt_assembly import (
        build_generation_user_prompt,
        lesson_curriculum_snippet_from_payload,
        lesson_generation_system_instruction,
        lesson_profile_block_from_snapshot,
        lesson_system_instruction,
        onboarding_system_instruction,
    )
    from app.services.skills import should_include_vocab_formats
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Could not import app.* — run from the repo root with "
        "PYTHONPATH=apps/backend python -m evals.run ..."
    ) from exc

from evals.checks import CheckContext, run_checks
from evals.judges.agreement import summarize_agreement
from evals.judges.runner import (
    RUBRIC_GENERATION,
    canned_to_result,
    judge_with_optional_repeats,
    load_canned_judge,
    resolve_rubric,
)
from evals.judges.schema import JudgeCallResult

SUITE_DIRS = {
    "capability": "cases/capability",
    "regression": "cases/regression",
    "calibration": "cases/calibration",
    "inbox": "cases/inbox",
}
GATED_SUITES = frozenset({"capability", "regression"})
MODES = ("onboarding", "lesson", "lesson_generation")
DEFAULT_BASELINE = EVALS_ROOT / "fixtures" / "baseline.json"


class CaseError(Exception):
    """Harness / fixture problem — always a case failure, never inverted by expect_fail."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run lingua-coach offline evals. Deterministic checks are the ship gate; "
            "LLM judges are informational."
        )
    )
    parser.add_argument(
        "--suite",
        choices=["capability", "regression", "calibration", "inbox", "all"],
        default="regression",
        help="calibration and inbox are reported but never fail the process (not a ship gate).",
    )
    parser.add_argument("--mode", choices=list(MODES), default=None)
    parser.add_argument("--id", dest="case_id", default=None, help="Run a single case id.")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Load replay completions; never call Gemini (tutor or judge).",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="JSON snapshot of prior failed_ids (default: evals/fixtures/baseline.json if present).",
    )
    parser.add_argument(
        "--self-consistency",
        nargs="?",
        const=3,
        type=int,
        default=None,
        metavar="N",
        help="Re-judge the same completion N times (live only; replay skips or uses canned).",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run judges after deterministic checks when checks.judge is set (default).",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip all judges (live and canned).",
    )
    parser.add_argument(
        "--agreement",
        action="store_true",
        help="Compare judge scores (live or canned) to labels: ; print %% agree and Cohen's κ.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help=(
            "Upload the experiment to LangSmith (needs LANGSMITH_API_KEY). "
            "Default is local only. Inbox stubs are not uploaded."
        ),
    )
    return parser.parse_args(argv)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CaseError(f"{path} did not parse as a mapping")
    return data


def _discover_suite_files(suite: str) -> list[Path]:
    rel = SUITE_DIRS.get(suite)
    if rel is None:
        return []
    folder = EVALS_ROOT / rel
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.suffix in {".yaml", ".yml"} and p.is_file()]
    return sorted(files)


def _suites_to_load(suite_arg: str) -> list[str]:
    if suite_arg == "all":
        return ["capability", "regression"]
    return [suite_arg]


def _load_fixture(case: dict[str, Any]) -> dict[str, Any]:
    inp = case.get("input") or {}
    rel = inp.get("context_fixture")
    if not rel:
        return {}
    path = EVALS_ROOT / str(rel)
    if not path.is_file():
        raise CaseError(f"context_fixture not found: {rel} (resolved {path})")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseError(f"context_fixture is not valid JSON: {rel}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaseError(f"context_fixture must be a JSON object: {rel}")
    return data


def _replay_stem(case: dict[str, Any], case_id: str) -> str:
    inp = case.get("input") or {}
    raw = inp.get("replay_from") or case.get("replay_from")
    if raw:
        return str(raw)
    return case_id


def _load_replay(case_id: str, case: dict[str, Any] | None = None) -> list[str]:
    stem = _replay_stem(case, case_id) if case else case_id
    path = EVALS_ROOT / "fixtures" / "replay" / f"{stem}.json"
    if not path.is_file():
        raise CaseError(f"replay fixture missing: fixtures/replay/{stem}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseError(f"replay fixture is not valid JSON: {path.name}: {exc}") from exc
    if isinstance(data, str):
        return [data]
    if not isinstance(data, dict):
        raise CaseError(f"replay fixture must be an object or string: {path.name}")
    if data.get("completions"):
        completions = data["completions"]
        if not isinstance(completions, list) or not completions:
            raise CaseError(f"replay completions must be a non-empty list: {path.name}")
        return [str(item) for item in completions]
    for key in ("raw_completion", "completion"):
        if key in data and data[key] is not None:
            return [str(data[key])]
    raise CaseError(
        f"replay fixture needs raw_completion or completions: fixtures/replay/{stem}.json"
    )


def _locale(case: dict[str, Any], fixture: dict[str, Any]) -> tuple[str | None, str | None]:
    loc = case.get("locale") or {}
    profile = fixture.get("learner_profile") or fixture.get("profile") or {}
    languages = profile.get("languages") if isinstance(profile, dict) else {}
    if not isinstance(languages, dict):
        languages = {}
    native = (
        loc.get("native")
        or fixture.get("native")
        or fixture.get("native_language")
        or languages.get("native")
        or (profile.get("native_language") if isinstance(profile, dict) else None)
    )
    target = (
        loc.get("target")
        or fixture.get("target")
        or fixture.get("target_language")
        or languages.get("target")
        or (profile.get("target_language") if isinstance(profile, dict) else None)
    )
    return (
        str(native) if native not in (None, "") else None,
        str(target) if target not in (None, "") else None,
    )


def _curriculum_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    curriculum = fixture.get("curriculum")
    if isinstance(curriculum, dict):
        return curriculum
    lesson = fixture.get("lesson")
    if isinstance(lesson, dict):
        payload = lesson.get("payload") or {}
        nested = payload.get("curriculum") if isinstance(payload, dict) else None
        if isinstance(nested, dict):
            return nested
        if isinstance(lesson.get("curriculum"), dict):
            return lesson["curriculum"]
    return {}


def _history_turns(case: dict[str, Any], fixture: dict[str, Any]) -> list[ChatTurn]:
    inp = case.get("input") or {}
    raw = inp.get("history")
    if raw is None:
        raw = fixture.get("history") or fixture.get("messages") or []
    if not isinstance(raw, list):
        raise CaseError("history must be a list of {role, text|content} turns")
    turns: list[ChatTurn] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CaseError("history items must be objects")
        role_raw = str(item.get("role") or "user")
        text = item.get("text")
        if text is None:
            text = item.get("content")
        if text is None:
            raise CaseError("history item missing text/content")
        role: Literal["user", "model"] = (
            "model" if role_raw in {"model", "assistant"} else "user"
        )
        turns.append(ChatTurn(role=role, text=str(text)))
    return turns


def _due_mistakes(fixture: dict[str, Any]) -> list[Any]:
    due = fixture.get("due_mistakes")
    if due is None:
        due = fixture.get("open_mistakes") or []
    if not isinstance(due, list):
        return []
    return due


def _goal_level(fixture: dict[str, Any]) -> tuple[str | None, str | None]:
    profile = fixture.get("learner_profile") or fixture.get("profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    goal_obj = profile.get("goal") if isinstance(profile.get("goal"), dict) else {}
    level_obj = profile.get("level") if isinstance(profile.get("level"), dict) else {}
    goal = (
        fixture.get("goal")
        or fixture.get("goal_outcome")
        or profile.get("goal_outcome")
        or (goal_obj.get("outcome") if isinstance(goal_obj, dict) else None)
    )
    level = (
        fixture.get("level")
        or fixture.get("target_level")
        or profile.get("target_level")
        or (level_obj.get("self_assessed") if isinstance(level_obj, dict) else None)
    )
    return (
        str(goal) if goal not in (None, "") else None,
        str(level) if level not in (None, "") else None,
    )


def _profile_snapshot_from_fixture(fixture: dict[str, Any]) -> dict[str, Any] | None:
    profile = fixture.get("learner_profile") or fixture.get("profile")
    if isinstance(profile, dict) and profile:
        return profile
    keys = (
        "goal_outcome",
        "native_language",
        "target_language",
        "target_level",
        "level_strengths",
        "level_weaknesses",
        "time_budget",
        "focus",
        "constraints",
        "grammar_mastery",
        "vocabulary_summary",
        "diagnostic_notes",
    )
    snap = {key: fixture[key] for key in keys if key in fixture}
    return snap or None


def _generation_context(fixture: dict[str, Any]) -> dict[str, Any]:
    gen = fixture.get("generation_context")
    if isinstance(gen, dict) and gen:
        return gen

    roadmap = fixture.get("roadmap")
    plan = fixture.get("active_plan")
    if not isinstance(plan, dict):
        current_idx = 0
        if isinstance(roadmap, dict):
            current_idx = roadmap.get("current_milestone_index") or 0
            block = roadmap.get("current_block")
            if isinstance(block, dict) and block.get("milestone_index") is not None:
                current_idx = block["milestone_index"]
        plan = {"roadmap": roadmap, "current_milestone_index": current_idx}

    mistakes = fixture.get("open_mistakes")
    if mistakes is None:
        mistakes = fixture.get("due_mistakes") or []

    return {
        "lesson_number": fixture.get("lesson_number", 1),
        "active_plan": plan,
        "learner_profile": _profile_snapshot_from_fixture(fixture),
        "prior_lessons": fixture.get("prior_lessons") or [],
        "open_mistakes": mistakes,
    }


def assemble_case(
    case: dict[str, Any], fixture: dict[str, Any]
) -> tuple[str, list[ChatTurn] | None, str | None]:
    """Return (system_instruction, chat_history_or_none, generation_user_prompt_or_none)."""
    mode = case.get("mode")
    native, target = _locale(case, fixture)
    inp = case.get("input") or {}
    user_message = inp.get("user_message")
    if user_message is not None:
        user_message = str(user_message)

    if mode == "onboarding":
        system = onboarding_system_instruction(native, target)
        history = _history_turns(case, fixture)
        if user_message is not None and user_message.strip():
            history.append(ChatTurn(role="user", text=user_message))
        if not history:
            raise CaseError("onboarding case needs input.user_message or fixture history")
        return system, history, None

    if mode == "lesson":
        curriculum = _curriculum_from_fixture(fixture)
        include_vocab = fixture.get("include_vocab")
        if include_vocab is None:
            include_vocab = should_include_vocab_formats(curriculum)
        system = lesson_system_instruction(native, target, bool(include_vocab))
        goal, level = _goal_level(fixture)
        context_block = (
            f"{lesson_curriculum_snippet_from_payload(curriculum)}\n\n"
            f"{lesson_profile_block_from_snapshot(native, target, goal, level, _due_mistakes(fixture))}"
        )
        history = _history_turns(case, fixture)
        if user_message is not None and user_message.strip():
            history.append(ChatTurn(role="user", text=user_message))
        if not history:
            raise CaseError("lesson case needs input.user_message or fixture history")
        contents = [ChatTurn(role="user", text=context_block), *history]
        return system, contents, None

    if mode == "lesson_generation":
        system = lesson_generation_system_instruction(native, target)
        context = _generation_context(fixture)
        prompt = build_generation_user_prompt(context)
        return system, None, prompt

    raise CaseError(f"unknown mode: {mode!r}")


def _deterministic_names(case: dict[str, Any]) -> list[str]:
    checks = case.get("checks") or {}
    if isinstance(checks, list):
        return [str(n) for n in checks]
    if isinstance(checks, dict):
        det = checks.get("deterministic") or []
        return [str(n) for n in det]
    return []


def _expect_fail(case: dict[str, Any]) -> bool:
    if case.get("expect_fail") is True:
        return True
    checks = case.get("checks")
    return isinstance(checks, dict) and checks.get("expect_fail") is True


def _judge_spec(case: dict[str, Any]) -> dict[str, Any] | None:
    checks = case.get("checks")
    if not isinstance(checks, dict):
        return None
    judge = checks.get("judge")
    if not isinstance(judge, dict):
        return None
    rubric = judge.get("rubric")
    if not rubric:
        return None
    return judge


def _case_labels(case: dict[str, Any]) -> dict[str, Any] | None:
    labels = case.get("labels")
    if isinstance(labels, dict) and labels:
        return labels
    return None


def score_case(
    *,
    case: dict[str, Any],
    fixture: dict[str, Any],
    completion: str,
    harness_error: str | None,
    suite: str,
) -> dict[str, Any]:
    """Score deterministic checks. `gate` is 0 only when the process should exit 1.

    `expect_fail` inverts a real check result. A harness error or an unknown
    check name is a gate failure either way.
    """
    if harness_error:
        return {
            "checks": 0,
            "gate": 0,
            "comment": harness_error,
            "checks_ok": False,
            "ran": False,
        }
    native, target = _locale(case, fixture)
    results = run_checks(
        _deterministic_names(case),
        CheckContext(
            raw_completion=completion,
            locale_native=native,
            locale_target=target,
            fixture=fixture,
            mode=str(case.get("mode") or ""),
            case=case,
        ),
    )
    unknown = [item for item in results if item.unknown]
    if unknown:
        return {
            "checks": 0,
            "gate": 0,
            "comment": unknown[0].detail,
            "checks_ok": False,
            "ran": True,
        }
    checks_ok = all(item.passed for item in results) if results else True
    if _expect_fail(case):
        passed = not checks_ok
        comment = "expect_fail: checks unexpectedly passed" if checks_ok else ""
    else:
        passed = checks_ok
        if checks_ok:
            comment = ""
        else:
            failed = [item.name for item in results if not item.passed]
            comment = "checks failed: " + ", ".join(failed)
    gate = 0 if suite in GATED_SUITES and not passed else 1
    return {
        "checks": 1 if passed else 0,
        "gate": gate,
        "comment": comment,
        "checks_ok": checks_ok,
        "ran": True,
    }


async def judge_case(
    *,
    case: dict[str, Any],
    case_id: str,
    suite: str,
    fixture: dict[str, Any],
    completion: str,
    checks_ok: bool,
    replay: bool,
    enable_judge: bool,
    self_consistency: int | None,
) -> dict[str, Any] | None:
    """Informational judge. Never raises, and its score is not a ship gate."""
    if not enable_judge:
        return None
    spec_raw = _judge_spec(case)
    if spec_raw is None:
        return None

    try:
        spec = resolve_rubric(str(spec_raw["rubric"]))
        if replay:
            canned = load_canned_judge(EVALS_ROOT, case_id)
            if canned is None:
                return JudgeCallResult(
                    rubric_version=spec.version,
                    source="skipped",
                    skip_reason="replay: no canned fixtures/replay/<id>.judge.json (Gemini not called)",
                ).as_record()
            return canned_to_result(canned, spec).as_record()

        if not checks_ok and suite in GATED_SUITES:
            return JudgeCallResult(
                rubric_version=spec.version,
                source="skipped",
                skip_reason="deterministic_failed",
            ).as_record()
        if not (completion or "").strip():
            return JudgeCallResult(
                rubric_version=spec.version,
                source="skipped",
                skip_reason="empty_completion",
            ).as_record()

        repeats = 1
        if self_consistency is not None and self_consistency > 1:
            repeats = self_consistency
        result = await judge_with_optional_repeats(
            spec,
            case=case,
            fixture=fixture,
            completion=completion,
            generate_json=generate_json,
            ChatTurn=ChatTurn,
            repeats=repeats,
        )
        return result.as_record()
    except KeyError as exc:
        return JudgeCallResult(
            rubric_version=str(spec_raw.get("rubric") or "unknown"),
            source="skipped",
            skip_reason=str(exc),
            error=str(exc),
        ).as_record()
    except Exception as exc:  # noqa: BLE001 — judges must not fail the ship gate
        return JudgeCallResult(
            rubric_version=str(spec_raw.get("rubric") or "unknown"),
            source="skipped",
            error=f"judge exception (informational, not a gate): {type(exc).__name__}: {exc}",
        ).as_record()


class _NoNetworkSession(requests.Session):
    """Answers LangSmith client calls without sending fixture text anywhere."""

    def request(self, method, url, **kwargs):  # type: ignore[override]
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = b"{}"
        response.headers["Content-Type"] = "application/json"
        return response


def _langsmith_client(*, upload: bool) -> Client:
    if upload:
        return Client()
    # Local runs still construct trace objects. Skip zstd so the client does not
    # warn, and the session below drops the bytes instead of posting them.
    os.environ["LANGSMITH_DISABLE_RUN_COMPRESSION"] = "true"
    return Client(
        api_url="http://127.0.0.1:9",
        api_key="local-only",
        info=LangSmithInfo(version="local"),
        session=_NoNetworkSession(),
    )


async def _target(inputs: dict[str, Any]) -> dict[str, Any]:
    """One example. Replay returns the frozen completion. Live lesson cases run the graph."""
    load_error = inputs.get("load_error")
    if load_error:
        return {"completion": "", "completions": [], "harness_error": str(load_error)}
    case = inputs["case"]
    case_id = str(inputs["case_id"])
    fixture = inputs.get("fixture") or {}
    mode = case.get("mode")
    try:
        if mode not in MODES:
            raise CaseError(f"mode must be one of {MODES}, got {mode!r}")
        system, history, prompt = assemble_case(case, fixture)
        if inputs.get("replay"):
            completions = _load_replay(case_id, case)
            if mode == "lesson_generation":
                state = await invoke_lesson_graph(
                    prompt=prompt or "",
                    system_instruction=system,
                    replay_completions=completions,
                )
                completions = list(state.get("completions") or completions)
            return {
                "completion": completions[-1],
                "completions": completions,
                "harness_error": None,
            }
        if mode == "lesson_generation":
            try:
                state = await invoke_lesson_graph(
                    prompt=prompt or "",
                    system_instruction=system,
                )
                completions = list(state.get("completions") or [])
            except LessonGenerationError as exc:
                completions = list(exc.completions)
            if not completions:
                raise CaseError("lesson graph returned no completion")
            return {
                "completion": completions[-1],
                "completions": completions,
                "harness_error": None,
            }
        if history is None:
            raise CaseError(f"{mode} case produced no chat history")
        parts: list[str] = []
        async for chunk in stream_chat(system_instruction=system, history=history):
            parts.append(chunk)
        text = "".join(parts)
        return {"completion": text, "completions": [text], "harness_error": None}
    except CaseError as exc:
        return {"completion": "", "completions": [], "harness_error": str(exc)}
    except GeminiError as exc:
        return {
            "completion": "",
            "completions": [],
            "harness_error": f"GeminiError {exc.code}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 — a target crash is a gated case error
        return {
            "completion": "",
            "completions": [],
            "harness_error": f"{type(exc).__name__}: {exc}",
        }


def _examples(loaded: list[tuple[Path, dict[str, Any]]], args: argparse.Namespace) -> list[Example]:
    examples: list[Example] = []
    for path, case in loaded:
        case_id = str(case.get("id") or path.stem)
        suite = str(case.get("suite") or path.parent.name)
        load_error = case.get("_load_error")
        fixture: dict[str, Any] = {}
        if not load_error:
            try:
                fixture = _load_fixture(case)
            except CaseError as exc:
                load_error = str(exc)
        examples.append(
            Example(
                id=uuid.uuid4(),
                inputs={
                    "case": case,
                    "case_id": case_id,
                    "suite": suite,
                    "fixture": fixture,
                    "replay": bool(args.replay),
                    "enable_judge": not args.no_judge,
                    "self_consistency": None if args.replay else args.self_consistency,
                    "load_error": load_error,
                },
                outputs={},
            )
        )
    return examples


def _load_cases(args: argparse.Namespace) -> list[tuple[Path, dict[str, Any]]]:
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for suite in _suites_to_load(args.suite):
        for path in _discover_suite_files(suite):
            try:
                case = _load_yaml(path)
            except (CaseError, OSError, yaml.YAMLError) as exc:
                loaded.append(
                    (
                        path,
                        {
                            "id": path.stem,
                            "suite": suite,
                            "mode": "onboarding",
                            "checks": {"deterministic": []},
                            "_load_error": str(exc),
                        },
                    )
                )
                continue
            case.setdefault("suite", suite)
            if args.mode and case.get("mode") != args.mode:
                continue
            if args.case_id and str(case.get("id") or path.stem) != args.case_id:
                continue
            loaded.append((path, case))
    return loaded


def _print_agreement(records: list[dict[str, Any]]) -> None:
    summary = summarize_agreement(records)
    print("Agreement (author-proposed labels vs judge)")
    dims = summary.get("dimensions") or {}
    if not dims:
        print("No overlapping labels + judge scores in this run.")
        return
    print(f"{'Dimension':<24} {'N':>4} {'% agree':>8} {'kappa':>8}")
    for name, row in dims.items():
        pct = row.get("percent_agree")
        kappa = row.get("cohens_kappa")
        pct_s = "—" if pct is None else f"{pct:.1%}"
        kap_s = "—" if kappa is None else f"{kappa:.3f}"
        print(f"{name:<24} {row.get('n', 0):>4} {pct_s:>8} {kap_s:>8}")


async def _evaluate(args: argparse.Namespace) -> int:
    if args.upload and not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY is required for --upload.", file=sys.stderr)
        return 1
    if args.upload and args.suite == "inbox":
        print("--upload does not upload inbox stubs.", file=sys.stderr)
        return 1

    loaded = _load_cases(args)
    if args.case_id and not loaded:
        print(f"No case with id {args.case_id!r} in suite {args.suite!r}.", file=sys.stderr)
        return 1
    if args.upload:
        kept: list[tuple[Path, dict[str, Any]]] = []
        dropped = False
        for path, case in loaded:
            suite = str(case.get("suite") or path.parent.name)
            if suite == "inbox":
                dropped = True
                continue
            kept.append((path, case))
        loaded = kept
        if dropped:
            print("Skipping inbox stubs; --upload does not send them.", file=sys.stderr)
    if not loaded:
        print("No cases matched (empty suite is a pass).")
        return 0

    scored: list[dict[str, Any]] = []
    judge_records: list[dict[str, Any]] = []
    summary_notes: list[str] = []

    def checks_evaluator(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
        row = score_case(
            case=inputs["case"],
            fixture=inputs.get("fixture") or {},
            completion=str((outputs or {}).get("completion") or ""),
            harness_error=(outputs or {}).get("harness_error"),
            suite=str(inputs.get("suite") or ""),
        )
        scored.append(
            {
                "id": inputs.get("case_id"),
                "suite": inputs.get("suite"),
                "checks": row["checks"],
                "gate": row["gate"],
                "comment": row["comment"],
                "checks_ok": row["checks_ok"],
            }
        )
        return {
            "results": [
                {"key": "checks", "score": row["checks"], "comment": row["comment"]},
                {"key": "gate", "score": row["gate"], "comment": row["comment"]},
            ]
        }

    async def judge_evaluator(
        inputs: dict, outputs: dict, reference_outputs: dict | None = None
    ) -> dict:
        if (outputs or {}).get("harness_error"):
            return {"key": "judge", "score": 1, "comment": "skipped: harness error"}
        scored_row = score_case(
            case=inputs["case"],
            fixture=inputs.get("fixture") or {},
            completion=str((outputs or {}).get("completion") or ""),
            harness_error=None,
            suite=str(inputs.get("suite") or ""),
        )
        record = await judge_case(
            case=inputs["case"],
            case_id=str(inputs["case_id"]),
            suite=str(inputs.get("suite") or ""),
            fixture=inputs.get("fixture") or {},
            completion=str((outputs or {}).get("completion") or ""),
            checks_ok=bool(scored_row["checks_ok"]),
            replay=bool(inputs.get("replay")),
            enable_judge=bool(inputs.get("enable_judge")),
            self_consistency=inputs.get("self_consistency"),
        )
        if record is not None:
            judge_records.append(
                {
                    "id": inputs.get("case_id"),
                    "labels": _case_labels(inputs["case"]),
                    "judge": record,
                }
            )
        return {"key": "judge", "score": 1, "comment": (record or {}).get("source") or "skipped"}

    def summary_evaluator(runs: list, examples: list) -> dict:
        path = Path(args.baseline) if args.baseline else DEFAULT_BASELINE
        baseline_failed: set[str] = set()
        found = path.is_file()
        if found:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("failed_ids"), list):
                baseline_failed = {str(item) for item in data["failed_ids"]}
        gated_failed = [str(row["id"]) for row in scored if row["gate"] == 0]
        new_failures = [item for item in gated_failed if item not in baseline_failed]
        if found:
            comment = "New failures vs baseline: " + (", ".join(new_failures) if new_failures else "none")
        else:
            comment = "Baseline: skipped (file missing)."
        summary_notes.append(comment)
        return {"key": "new_failures", "score": 0 if new_failures else 1, "comment": comment}

    warnings.filterwarnings("ignore", message="'upload_results' parameter is in beta.")
    client = _langsmith_client(upload=bool(args.upload))
    results = await client.aevaluate(
        _target,
        data=_examples(loaded, args),
        evaluators=[checks_evaluator, judge_evaluator],
        summary_evaluators=[summary_evaluator],
        upload_results=bool(args.upload),
        max_concurrency=1,
        experiment_prefix="lingua-coach",
        metadata={
            "replay": bool(args.replay),
            "suite": args.suite,
            "rubric_version": RUBRIC_GENERATION,
        },
        error_handling="log",
        disable_evaluator_tracing=not args.upload,
    )
    async for _row in results:
        pass

    failures = [row for row in scored if row["gate"] == 0]
    gated_pass = sum(
        1 for row in scored if row["suite"] in GATED_SUITES and row["gate"] == 1 and row["checks"] == 1
    )
    print(f"Gated pass/fail: {gated_pass} pass / {len(failures)} fail")
    for row in failures:
        print(f"- {row['id']}: {row['comment'] or 'failed'}")
    for note in summary_notes:
        print(note)
    if args.self_consistency and args.replay:
        print("Self-consistency skipped in --replay (no live Gemini). Canned .judge.json is a single trial.")
    flips = []
    for record in judge_records:
        judge = record.get("judge") or {}
        consistency = judge.get("self_consistency") if isinstance(judge, dict) else None
        if isinstance(consistency, dict) and consistency.get("flips"):
            flips.append(f"{record['id']}: {', '.join(consistency['flips'])}")
    if flips:
        print("Self-consistency flips: " + "; ".join(flips))
    if args.agreement:
        _print_agreement(judge_records)
    if not scored:
        print("No cases matched (empty suite is a pass).")
        return 0
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(_evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())

