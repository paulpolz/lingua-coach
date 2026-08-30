"""CI-visible parse/repair tests for evals judges (no live Gemini, no Postgres)."""

from __future__ import annotations

import sys
from pathlib import Path

# evals/ lives at the repo root; backend pytest cwd is apps/backend.
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.tests.test_judges import (  # noqa: E402
    test_canned_invalid_scores_do_not_raise,
    test_canned_judge_fixture_parses,
    test_cohen_kappa_perfect_and_chance,
    test_flipped_dimensions,
    test_judge_once_records_error_after_failed_repair,
    test_judge_once_repairs_after_invalid_first_call,
    test_maybe_judge_swallows_exceptions,
    test_parse_fenced_json,
    test_parse_normalizes_yes_no,
    test_parse_plain_json,
    test_parse_rejects_invalid_score,
    test_parse_rejects_missing_dimension,
    test_parse_rejects_non_json,
    test_repair_prompt_includes_error_and_previous,
    test_summarize_agreement,
)

__all__ = [
    "test_canned_invalid_scores_do_not_raise",
    "test_canned_judge_fixture_parses",
    "test_cohen_kappa_perfect_and_chance",
    "test_flipped_dimensions",
    "test_maybe_judge_swallows_exceptions",
    "test_parse_fenced_json",
    "test_parse_normalizes_yes_no",
    "test_parse_plain_json",
    "test_parse_rejects_invalid_score",
    "test_parse_rejects_missing_dimension",
    "test_parse_rejects_non_json",
    "test_judge_once_records_error_after_failed_repair",
    "test_judge_once_repairs_after_invalid_first_call",
    "test_repair_prompt_includes_error_and_previous",
    "test_summarize_agreement",
]
