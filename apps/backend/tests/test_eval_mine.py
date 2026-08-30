"""CI-visible tests for evals.mine (no live Gemini, no Postgres)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.tests.test_mine import (  # noqa: E402
    test_dedupe_keeps_newest,
    test_hits_from_lessons_and_jobs,
    test_hits_from_mistakes_requires_high_count_and_correction,
    test_hits_from_quality_events_filters_upvotes_and_high_csat,
    test_main_exits_when_database_url_missing,
    test_parse_args_defaults,
    test_regression_suite_does_not_load_inbox,
    test_resolve_database_url_fails_when_missing,
    test_resolve_database_url_prefers_cli_and_normalizes,
    test_strip_pii_redacts_email_and_uuid,
    test_stub_yaml_is_inbox_and_omits_transcript,
    test_tag_job_fail_schema,
    test_tag_thumbs_down_and_immersion,
    test_tag_too_hard_feedback,
    test_truncate_user_text,
    test_write_stubs_respects_limit_and_dry_run,
)

__all__ = [
    "test_dedupe_keeps_newest",
    "test_hits_from_lessons_and_jobs",
    "test_hits_from_mistakes_requires_high_count_and_correction",
    "test_hits_from_quality_events_filters_upvotes_and_high_csat",
    "test_main_exits_when_database_url_missing",
    "test_parse_args_defaults",
    "test_regression_suite_does_not_load_inbox",
    "test_resolve_database_url_fails_when_missing",
    "test_resolve_database_url_prefers_cli_and_normalizes",
    "test_strip_pii_redacts_email_and_uuid",
    "test_stub_yaml_is_inbox_and_omits_transcript",
    "test_tag_job_fail_schema",
    "test_tag_thumbs_down_and_immersion",
    "test_tag_too_hard_feedback",
    "test_truncate_user_text",
    "test_write_stubs_respects_limit_and_dry_run",
]
