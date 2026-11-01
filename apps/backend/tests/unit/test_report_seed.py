"""Seeded report markdown."""

from __future__ import annotations

from app.services.report_seed import seed_four_week_plan_markdown, seed_roadmap_markdown
from tests.samples import roadmap


def test_seeded_reports_never_print_none_for_empty_optional_fields() -> None:
    dumped = roadmap().model_dump()  # what accept stores: optional keys present with None
    dumped["weekly_template"] = {"minutes_per_session": 15, "activities": [], "partner_session": None, "weekends": None}
    dumped["current_block"] = {"milestone_index": 0, "weeks": None, "focus_summary": None, "themes": [{"block_day": 1}]}
    for body in (seed_roadmap_markdown(dumped), seed_four_week_plan_markdown(dumped)):
        assert "None" not in body
    assert "**Learning language:** —" in seed_roadmap_markdown(dumped)
