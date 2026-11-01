"""Seeded report markdown."""

from __future__ import annotations

from app.services.report_seed import blank_progress_markdown, seed_four_week_plan_markdown, seed_roadmap_markdown
from tests.factories import roadmap_dict
from tests.samples import roadmap


def test_progress_table_has_no_listening_or_speaking_row() -> None:
    body = blank_progress_markdown()
    assert "Listening" not in body and "Speaking" not in body
    assert "| Writing |" in body


def test_four_week_plan_uses_theme_fields_and_lesson_length() -> None:
    roadmap = roadmap_dict(
        weekly_template={"minutes_per_session": 15, "sessions_per_week": 5, "weekends": "light review"},
        current_block={
            "milestone_index": 0,
            "themes": [
                {
                    "block_day": 1,
                    "grammar_focus": "Present simple",
                    "vocab_theme": "Self",
                    "goal_context": "Intro email",
                }
            ],
        },
    )
    body = seed_four_week_plan_markdown(roadmap)
    assert "| Goal context | Intro email |" in body
    assert "15 min per lesson · 5 lessons/week" in body
    assert "light review" in body


def test_four_week_plan_tolerates_legacy_roadmaps() -> None:
    legacy = roadmap_dict(
        weekly_template={"minutes_per_session": 60, "activities": [{"id": "warmup", "label": "W", "minutes": 5}]},
        current_block={"milestone_index": 0, "themes": [{"block_day": 1, "input_type": "reading"}]},
    )
    body = seed_four_week_plan_markdown(legacy)
    assert "60 min per lesson" in body
    assert "warmup" not in body


def test_seeded_reports_never_print_none_for_empty_optional_fields() -> None:
    dumped = roadmap().model_dump()  # what accept stores: optional keys present with None
    dumped["weekly_template"] = {"minutes_per_session": 15, "sessions_per_week": None, "weekends": None}
    dumped["current_block"] = {"milestone_index": 0, "weeks": None, "focus_summary": None, "themes": [{"block_day": 1}]}
    for body in (seed_roadmap_markdown(dumped), seed_four_week_plan_markdown(dumped)):
        assert "None" not in body
    assert "**Learning language:** —" in seed_roadmap_markdown(dumped)
