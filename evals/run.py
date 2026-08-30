"""Offline eval runner — assemble production prompts, replay or call Gemini, run checks.

From repo root:

    PYTHONPATH=apps/backend python -m evals.run --suite regression --replay
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
    from pydantic import ValidationError

    from app.config import settings
    from app.services.gemini import ChatTurn, GeminiError, generate_json, stream_chat
    from app.services.lesson_generation import _build_repair_prompt, _parse_curriculum
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
    RUBRICS,
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


def _git_rev_parse(ref: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_sha() -> str | None:
    """Repo HEAD commit SHA."""
    return _git_rev_parse("HEAD")


def _skill_sha() -> tuple[str | None, str]:
    """Git tree SHA of `skills/` at HEAD (`git rev-parse HEAD:skills`).

    Falls back to repo HEAD if the skills tree is unavailable. See
    evals/docs/methodology.md — `skill_sha` is the skills tree when present.
    """
    tree = _git_rev_parse("HEAD:skills")
    if tree:
        return tree, "skills_tree"
    return _git_sha(), "repo_head"


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


async def _stream_once(system_instruction: str, history: list[ChatTurn]) -> str:
    parts: list[str] = []
    async for chunk in stream_chat(system_instruction=system_instruction, history=history):
        parts.append(chunk)
    return "".join(parts)


async def _generate_with_optional_repair(
    system_instruction: str, prompt: str
) -> list[str]:
    """Match production: one generate_json, then at most one schema repair."""
    completions: list[str] = []
    raw = await generate_json(
        system_instruction=system_instruction,
        history=[ChatTurn(role="user", text=prompt)],
    )
    completions.append(raw)
    try:
        _parse_curriculum(raw)
        return completions
    except (json.JSONDecodeError, ValidationError) as exc:
        repair_prompt = _build_repair_prompt(prompt, raw, exc)
        raw_retry = await generate_json(
            system_instruction=system_instruction,
            history=[ChatTurn(role="user", text=repair_prompt)],
        )
        completions.append(raw_retry)
        return completions


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


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        path = DEFAULT_BASELINE if DEFAULT_BASELINE.is_file() else None
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _maybe_judge(
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
    """Informational only — never used as a ship-gate signal. Never raises."""
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
            from evals.judges.runner import canned_to_result

            return canned_to_result(canned, spec).as_record()

        # Live: skip unusable output on gated suites; calibration still scores fail labels.
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


async def _run_case(
    *,
    case: dict[str, Any],
    source: Path,
    replay: bool,
    enable_judge: bool,
    self_consistency: int | None,
) -> dict[str, Any]:
    case_id = str(case.get("id") or source.stem)
    suite = str(case.get("suite") or source.parent.name)
    mode = case.get("mode")
    labels = _case_labels(case)
    record: dict[str, Any] = {
        "id": case_id,
        "suite": suite,
        "mode": mode,
        "path": str(source.relative_to(EVALS_ROOT)),
        "expect_fail": _expect_fail(case),
        "gated": suite in GATED_SUITES,
        "passed": False,
        "error": None,
        "checks": [],
        "completions": [],
        "judge": None,
        "labels": labels,
    }
    try:
        if mode not in MODES:
            raise CaseError(f"mode must be one of {MODES}, got {mode!r}")
        fixture = _load_fixture(case)
        native, target = _locale(case, fixture)
        system, history, gen_prompt = assemble_case(case, fixture)

        if replay:
            completions = _load_replay(case_id, case)
        elif mode == "lesson_generation":
            assert gen_prompt is not None
            completions = await _generate_with_optional_repair(system, gen_prompt)
        else:
            assert history is not None
            completions = [await _stream_once(system, history)]

        record["completions"] = completions
        raw = completions[-1]
        check_names = _deterministic_names(case)
        ctx = CheckContext(
            raw_completion=raw,
            locale_native=native,
            locale_target=target,
            fixture=fixture,
            mode=str(mode),
            case=case,
        )
        results = run_checks(check_names, ctx)
        record["checks"] = [
            {"name": r.name, "passed": r.passed, "detail": r.detail, "unknown": r.unknown}
            for r in results
        ]
        unknown = [r for r in results if r.unknown]
        if unknown:
            record["error"] = unknown[0].detail
            record["passed"] = False
            record["gated"] = True
            record["judge"] = await _maybe_judge(
                case=case,
                case_id=case_id,
                suite=suite,
                fixture=fixture,
                completion=raw,
                checks_ok=False,
                replay=replay,
                enable_judge=enable_judge,
                self_consistency=self_consistency,
            )
            return record

        checks_ok = all(r.passed for r in results) if results else True
        if record["expect_fail"]:
            record["passed"] = not checks_ok
            if checks_ok:
                record["error"] = "expect_fail: checks unexpectedly passed"
        else:
            record["passed"] = checks_ok
            if not checks_ok:
                failed = [r.name for r in results if not r.passed]
                record["error"] = "checks failed: " + ", ".join(failed)

        record["judge"] = await _maybe_judge(
            case=case,
            case_id=case_id,
            suite=suite,
            fixture=fixture,
            completion=raw,
            checks_ok=checks_ok,
            replay=replay,
            enable_judge=enable_judge,
            self_consistency=self_consistency,
        )
    except CaseError as exc:
        record["error"] = str(exc)
        record["passed"] = False
        record["gated"] = True
    except GeminiError as exc:
        record["error"] = f"GeminiError {exc.code}: {exc}"
        record["passed"] = False
        record["gated"] = True
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
        record["passed"] = False
        record["gated"] = True
    return record


def _markdown_summary(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"# Eval run `{payload['run_id']}`",
        "",
        f"- replay: `{payload['replay']}`",
        f"- suite filter: `{payload['suite']}`",
        f"- model: `{payload.get('model')}`",
        f"- model_chat: `{payload.get('model_chat')}`",
        f"- model_lesson: `{payload.get('model_lesson')}`",
        f"- skill_sha: `{payload.get('skill_sha')}` ({payload.get('skill_sha_source')})",
        f"- rubric_version: `{payload.get('rubric_version')}`",
        "",
        "| Suite | Pass | Fail |",
        "| --- | ---: | ---: |",
    ]
    by_suite = summary.get("by_suite") or {}
    for name in sorted(by_suite):
        row = by_suite[name]
        lines.append(f"| {name} | {row['passed']} | {row['failed']} |")
    lines.extend(
        [
            "",
            f"**Gated pass/fail:** {summary['gated_passed']} pass / {summary['gated_failed']} fail",
        ]
    )
    failed_ids = summary.get("failed_ids") or []
    if failed_ids:
        lines.append("")
        lines.append("Failed cases:")
        for case in payload["cases"]:
            if case["id"] in failed_ids:
                lines.append(f"- `{case['id']}` — {case.get('error') or 'failed'}")
    new_failures = summary.get("new_failures") or []
    resolved = summary.get("resolved") or []
    if payload.get("baseline_path"):
        lines.append("")
        lines.append(f"Baseline: `{payload['baseline_path']}`")
        lines.append(
            "New failures vs baseline: "
            + (", ".join(f"`{i}`" for i in new_failures) if new_failures else "none")
        )
        if resolved:
            lines.append("Resolved vs baseline: " + ", ".join(f"`{i}`" for i in resolved))
    else:
        lines.append("")
        lines.append("Baseline: skipped (file missing).")
    agreement = payload.get("agreement")
    if agreement:
        lines.append("")
        lines.append("## Agreement (author-proposed labels vs judge)")
        lines.append("")
        lines.append(agreement.get("note") or "")
        dims = agreement.get("dimensions") or {}
        if dims:
            lines.append("")
            lines.append("| Dimension | N | % agree | Cohen's κ |")
            lines.append("| --- | ---: | ---: | ---: |")
            for name, row in dims.items():
                pct = row.get("percent_agree")
                kappa = row.get("cohens_kappa")
                pct_s = "—" if pct is None else f"{pct:.1%}"
                kap_s = "—" if kappa is None else f"{kappa:.3f}"
                lines.append(f"| {name} | {row.get('n', 0)} | {pct_s} | {kap_s} |")
        else:
            lines.append("No overlapping labels + judge scores in this run.")
    flips_rows = payload.get("self_consistency_flips") or []
    if payload.get("self_consistency_n"):
        lines.append("")
        lines.append(f"## Self-consistency (N={payload['self_consistency_n']})")
        if payload.get("self_consistency_skipped"):
            lines.append("")
            lines.append(str(payload["self_consistency_skipped"]))
        elif flips_rows:
            lines.append("")
            for row in flips_rows:
                lines.append(f"- `{row['id']}` — flips: {', '.join(row['flips'])}")
        else:
            lines.append("")
            lines.append("No dimension flips (or no live judge trials).")
    judged = [c for c in payload.get("cases") or [] if isinstance(c.get("judge"), dict)]
    skipped = sum(1 for c in judged if c["judge"].get("source") == "skipped")
    scored = sum(1 for c in judged if c["judge"].get("scores"))
    if judged:
        lines.append("")
        lines.append(
            f"Judges (informational): {scored} scored / {skipped} skipped / "
            f"{len(judged)} considered. Not a ship gate."
        )
    return "\n".join(lines) + "\n"


async def async_main(args: argparse.Namespace) -> int:
    suites = _suites_to_load(args.suite)
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for suite in suites:
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

    if args.case_id and not loaded:
        print(f"No case with id {args.case_id!r} in suite {args.suite!r}.", file=sys.stderr)
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records: list[dict[str, Any]] = []
    for path, case in loaded:
        load_error = case.pop("_load_error", None)
        if load_error:
            records.append(
                {
                    "id": str(case.get("id") or path.stem),
                    "suite": str(case.get("suite") or path.parent.name),
                    "mode": case.get("mode"),
                    "path": str(path.relative_to(EVALS_ROOT)),
                    "expect_fail": False,
                    "gated": True,
                    "passed": False,
                    "error": load_error,
                    "checks": [],
                    "completions": [],
                }
            )
            continue
        records.append(
            await _run_case(
                case=case,
                source=path,
                replay=args.replay,
                enable_judge=not args.no_judge,
                self_consistency=None if args.replay else args.self_consistency,
            )
        )

    baseline_arg = Path(args.baseline) if args.baseline else None
    baseline = _load_baseline(baseline_arg)
    baseline_failed: set[str] = set()
    if baseline and isinstance(baseline.get("failed_ids"), list):
        baseline_failed = {str(i) for i in baseline["failed_ids"]}
    baseline_path_out: str | None = None
    if baseline is not None:
        used = baseline_arg or DEFAULT_BASELINE
        try:
            baseline_path_out = str(used.resolve().relative_to(REPO_ROOT))
        except ValueError:
            baseline_path_out = str(used)

    by_suite: dict[str, dict[str, int]] = {}
    failed_ids: list[str] = []
    gated_failed_ids: list[str] = []
    gated_passed = 0
    gated_failed = 0
    for rec in records:
        suite = rec["suite"]
        by_suite.setdefault(suite, {"passed": 0, "failed": 0})
        if rec["passed"]:
            by_suite[suite]["passed"] += 1
        else:
            by_suite[suite]["failed"] += 1
            failed_ids.append(rec["id"])
        if rec.get("gated"):
            if rec["passed"]:
                gated_passed += 1
            else:
                gated_failed += 1
                gated_failed_ids.append(rec["id"])

    new_failures = [i for i in gated_failed_ids if i not in baseline_failed]
    resolved = [i for i in sorted(baseline_failed) if i not in set(gated_failed_ids)]

    skill_sha, skill_sha_source = _skill_sha()
    agreement_payload = None
    if args.agreement:
        agreement_payload = summarize_agreement(records)

    self_consistency_flips: list[dict[str, Any]] = []
    for rec in records:
        judge = rec.get("judge") or {}
        sc = judge.get("self_consistency") if isinstance(judge, dict) else None
        if isinstance(sc, dict) and sc.get("flips"):
            self_consistency_flips.append({"id": rec["id"], "flips": sc["flips"]})

    self_consistency_skipped = None
    if args.self_consistency and args.replay:
        self_consistency_skipped = (
            "Self-consistency skipped in --replay (no live Gemini). "
            "Canned .judge.json is a single trial."
        )

    payload = {
        "run_id": run_id,
        "replay": args.replay,
        "suite": args.suite,
        "mode": args.mode,
        "model": settings.gemini_model_lesson,
        "model_chat": settings.gemini_model_chat,
        "model_lesson": settings.gemini_model_lesson,
        "skill_sha": skill_sha,
        "skill_sha_source": skill_sha_source,
        "git_sha": _git_sha(),
        "rubric_version": RUBRIC_GENERATION,
        "rubric_versions": sorted(RUBRICS),
        "baseline_path": baseline_path_out,
        "agreement": agreement_payload,
        "self_consistency_n": args.self_consistency,
        "self_consistency_flips": self_consistency_flips,
        "self_consistency_skipped": self_consistency_skipped,
        "cases": records,
        "summary": {
            "passed": sum(1 for r in records if r["passed"]),
            "failed": sum(1 for r in records if not r["passed"]),
            "gated_passed": gated_passed,
            "gated_failed": gated_failed,
            "failed_ids": failed_ids,
            "gated_failed_ids": gated_failed_ids,
            "new_failures": new_failures,
            "resolved": resolved,
            "by_suite": by_suite,
        },
    }

    results_dir = EVALS_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = _markdown_summary(payload)
    print(md)
    print(f"Wrote {out_path.relative_to(REPO_ROOT)}")

    if not records:
        print("No cases matched (empty suite is a pass).")
        return 0
    if gated_failed:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
