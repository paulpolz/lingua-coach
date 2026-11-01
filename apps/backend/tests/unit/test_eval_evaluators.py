"""Deterministic eval checks (evals/evaluators.py)."""

from __future__ import annotations

import pytest

from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown
from evals.evaluators import (
    EVALUATORS,
    correction_spans_in_message,
    curriculum_has_no_speaking,
    curriculum_has_no_urls,
    reply_language_matches,
    report_ops_target_existing_sections,
    schema_parsed,
    suggest_finish_respects_time,
)

REPORTS = {"progress": blank_progress_markdown(), "errors_log": blank_errors_log_markdown()}


def test_schema_parsed() -> None:
    assert schema_parsed({"parsed": {"content": "x"}, "error": None}) == 1.0
    assert schema_parsed({"parsed": None, "error": "LLM_SCHEMA_ERROR"}) == 0.0


def test_curriculum_checks_find_urls_and_speaking() -> None:
    clean = {"lesson_goal": "Write an email", "new_vocabulary": ["deadline"]}
    assert curriculum_has_no_urls(clean) == curriculum_has_no_speaking(clean) == 1.0
    assert curriculum_has_no_urls({"goal_context": "read https://example.com"}) == 0.0
    assert curriculum_has_no_speaking({"practice_targets": ["Speak for 2 minutes"]}) == 0.0


def test_report_ops_must_hit_existing_sections_and_never_patch_logs() -> None:
    ok = [{"report_type": "progress", "op": "append_entry", "section_id": "update_log"}]
    unknown = [{"report_type": "progress", "op": "patch_section", "section_id": "invented"}]
    patch_log = [{"report_type": "errors_log", "op": "patch_section", "section_id": "daily_log"}]
    assert report_ops_target_existing_sections(ok, REPORTS) == 1.0
    assert report_ops_target_existing_sections(unknown, REPORTS) == 0.0
    assert report_ops_target_existing_sections(patch_log, REPORTS) == 0.0


@pytest.mark.parametrize(
    ("content", "target", "score"),
    [
        ("Great, and what is your goal with this?", "en", 1.0),
        ("¿Y cuál es tu objetivo con el español?", "es", 1.0),
        ("Great, and what is your goal with this?", "es", 0.0),
        ("Отлично! Какая у вас цель?", "ru", 1.0),
        ("Great, what is your goal?", "ru", 0.0),
        ("Hyvä!", "fi", None),
    ],
)
def test_reply_language_heuristic(content: str, target: str, score: float | None) -> None:
    assert reply_language_matches(content, target) == score


@pytest.mark.parametrize(
    ("suggest", "active", "target", "score"), [(True, 6, 15, 0.0), (True, 14, 15, 1.0), (False, 6, 15, 1.0)]
)
def test_suggest_finish_respects_time(suggest: bool, active: int, target: int, score: float) -> None:
    assert suggest_finish_respects_time(suggest, active, target) == score


def test_correction_spans_must_come_from_the_learner_message() -> None:
    assert correction_spans_in_message([{"span": "sent report"}], "I have sent report to client.") == 1.0
    assert correction_spans_in_message([{"span": "invented"}], "I have sent report.") == 0.0
    assert correction_spans_in_message([], "anything") == 1.0


def test_langsmith_adapters_score_a_failed_parse_as_zero() -> None:
    inputs = {"target": "en", "active_minutes": 6, "target_minutes": 15, "history": [{"role": "user", "text": "hi"}]}
    for evaluator in EVALUATORS["lesson_turns"]:
        assert evaluator(inputs, {"parsed": None, "error": "LLM_TIMEOUT"}, {})["score"] == 0.0
