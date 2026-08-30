"""Judge JSON parse / repair — mock Gemini, no API key."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.judges.agreement import cohen_kappa, percent_agree, summarize_agreement
from evals.judges.lesson_turn_v1 import DIMENSIONS as TURN_DIMS
from evals.judges.schema import JudgeParseError, build_repair_prompt, parse_judge_verdict
from evals.judges.runner import canned_to_result, flipped_dimensions, resolve_rubric

VALID = {
    "scores": {
        "immersion": "pass",
        "correction_accuracy": "fail",
        "pedagogy": "pass",
        "contract": "pass",
    },
    "rationale": {"immersion": "Spanish only"},
    "span": "you should say",
}


def test_parse_plain_json() -> None:
    verdict = parse_judge_verdict(
        json.dumps(VALID), dimensions=TURN_DIMS, rubric_version="lesson_turn_v1"
    )
    assert verdict.scores["immersion"] == "pass"
    assert verdict.scores["correction_accuracy"] == "fail"
    assert verdict.span == "you should say"
    assert verdict.rubric_version == "lesson_turn_v1"


def test_parse_fenced_json() -> None:
    raw = "Here you go:\n```json\n" + json.dumps(VALID) + "\n```\n"
    verdict = parse_judge_verdict(raw, dimensions=TURN_DIMS, rubric_version="lesson_turn_v1")
    assert verdict.scores["pedagogy"] == "pass"


def test_parse_normalizes_yes_no() -> None:
    payload = {
        "scores": {
            "immersion": "yes",
            "correction_accuracy": "NO",
            "pedagogy": True,
            "contract": False,
        },
        "rationale": "ok",
    }
    verdict = parse_judge_verdict(
        json.dumps(payload), dimensions=TURN_DIMS, rubric_version="lesson_turn_v1"
    )
    assert verdict.scores == {
        "immersion": "pass",
        "correction_accuracy": "fail",
        "pedagogy": "pass",
        "contract": "fail",
    }


def test_parse_rejects_missing_dimension() -> None:
    bad = {"scores": {"immersion": "pass"}, "rationale": ""}
    with pytest.raises(JudgeParseError, match="missing"):
        parse_judge_verdict(json.dumps(bad), dimensions=TURN_DIMS, rubric_version="lesson_turn_v1")


def test_parse_rejects_invalid_score() -> None:
    bad = {
        "scores": {
            "immersion": "maybe",
            "correction_accuracy": "pass",
            "pedagogy": "pass",
            "contract": "pass",
        }
    }
    with pytest.raises(JudgeParseError, match="invalid"):
        parse_judge_verdict(json.dumps(bad), dimensions=TURN_DIMS, rubric_version="lesson_turn_v1")


def test_parse_rejects_non_json() -> None:
    with pytest.raises(JudgeParseError, match="not a JSON object"):
        parse_judge_verdict("not json", dimensions=TURN_DIMS, rubric_version="lesson_turn_v1")


def test_repair_prompt_includes_error_and_previous() -> None:
    prompt = build_repair_prompt("SCORE THIS", "{bad", JudgeParseError("scores must be an object"))
    assert "SCORE THIS" in prompt
    assert "{bad" in prompt
    assert "scores must be an object" in prompt
    assert "ONLY a corrected JSON object" in prompt


@pytest.mark.asyncio
async def test_judge_once_repairs_after_invalid_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals.judges.runner import judge_once
    from evals.judges.lesson_turn_v1 import SPEC

    calls: list[str] = []

    async def fake_generate_json(*, system_instruction: str, history: list) -> str:
        text = history[-1].text
        calls.append(text)
        if len(calls) == 1:
            return "not-json"
        return json.dumps(VALID)

    class Turn:
        def __init__(self, role: str, text: str) -> None:
            self.role = role
            self.text = text

    result = await judge_once(
        SPEC,
        case={"mode": "lesson", "locale": {"native": "en", "target": "es"}, "input": {}},
        fixture={},
        completion="Hola.",
        generate_json=fake_generate_json,
        ChatTurn=Turn,
    )
    assert result.source == "live"
    assert result.repaired is True
    assert result.scores == VALID["scores"]
    assert result.error is None
    assert len(calls) == 2
    assert "Validation error" in calls[1]


@pytest.mark.asyncio
async def test_judge_once_records_error_after_failed_repair() -> None:
    from evals.judges.runner import judge_once
    from evals.judges.lesson_turn_v1 import SPEC

    async def always_bad(*, system_instruction: str, history: list) -> str:
        return "still-not-json"

    class Turn:
        def __init__(self, role: str, text: str) -> None:
            self.role = role
            self.text = text

    result = await judge_once(
        SPEC,
        case={"mode": "lesson", "locale": {"native": "en", "target": "es"}, "input": {}},
        fixture={},
        completion="Hola.",
        generate_json=always_bad,
        ChatTurn=Turn,
    )
    assert result.source == "live"
    assert result.repaired is True
    assert result.scores is None
    assert result.error and "after one repair" in result.error


def test_canned_judge_fixture_parses() -> None:
    evals_root = Path(__file__).resolve().parents[1]
    path = evals_root / "fixtures" / "replay" / "cal_lesson_chat_immersion_es_001.judge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    spec = resolve_rubric("lesson_turn_v1")
    result = canned_to_result(data, spec)
    assert result.source == "canned"
    assert result.scores is not None
    assert result.scores["immersion"] == "pass"


def test_cohen_kappa_perfect_and_chance() -> None:
    assert cohen_kappa(["pass", "fail"], ["pass", "fail"]) == 1.0
    # Same labels both sides, opposite of each other → κ = -1
    assert cohen_kappa(["pass", "fail"], ["fail", "pass"]) == -1.0
    assert percent_agree(["pass", "pass", "fail"], ["pass", "fail", "fail"]) == pytest.approx(2 / 3)
    assert cohen_kappa(["pass"], ["pass"]) is None


def test_flipped_dimensions() -> None:
    trials = [
        {"scores": {"immersion": "pass", "pedagogy": "pass"}},
        {"scores": {"immersion": "fail", "pedagogy": "pass"}},
        {"scores": {"immersion": "pass", "pedagogy": "pass"}},
    ]
    assert flipped_dimensions(trials, ("immersion", "pedagogy")) == ["immersion"]


def test_summarize_agreement() -> None:
    records = [
        {
            "labels": {"immersion": "pass", "pedagogy": "fail"},
            "judge": {"scores": {"immersion": "pass", "pedagogy": "fail"}},
        },
        {
            "labels": {"immersion": "fail", "pedagogy": "fail"},
            "judge": {"scores": {"immersion": "fail", "pedagogy": "pass"}},
        },
    ]
    summary = summarize_agreement(records)
    assert summary["dimensions"]["immersion"]["n"] == 2
    assert summary["dimensions"]["immersion"]["percent_agree"] == 1.0
    assert summary["dimensions"]["pedagogy"]["percent_agree"] == 0.5


def test_canned_invalid_scores_do_not_raise() -> None:
    spec = resolve_rubric("lesson_turn_v1")
    result = canned_to_result(
        {
            "scores": {"immersion": "maybe", "pedagogy": "pass"},
            "rationale": ["not", "a", "string"],
        },
        spec,
    )
    assert result.source == "canned"
    assert result.scores == {"pedagogy": "pass"}
    assert result.error


@pytest.mark.asyncio
async def test_maybe_judge_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals.run import _maybe_judge

    def boom(_name: str):
        raise RuntimeError("rubric lookup exploded")

    monkeypatch.setattr("evals.run.resolve_rubric", boom)
    record = await _maybe_judge(
        case={"checks": {"judge": {"rubric": "lesson_turn_v1"}}},
        case_id="gated_case",
        suite="regression",
        fixture={},
        completion="Hola.",
        checks_ok=True,
        replay=False,
        enable_judge=True,
        self_consistency=None,
    )
    assert record is not None
    assert record["source"] == "skipped"
    assert "not a gate" in (record.get("error") or "")
    assert record["rubric_version"] == "lesson_turn_v1"
