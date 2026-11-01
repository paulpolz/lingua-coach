"""Initial markdown for the four coach reports."""

from __future__ import annotations

from app.services.report_ops import wrap_section

_EMPTY = "—"


def _v(value: object) -> object:
    """A stored roadmap is `model_dump()`, so optional fields are present as None."""
    return _EMPTY if value is None or value == "" else value


def seed_roadmap_markdown(roadmap: dict) -> str:
    summary = roadmap.get("summary") or {}
    milestones = (
        "\n\n".join(
            f"### {(m.get('index') if m.get('index') is not None else i) + 1}. {_v(m.get('title'))}\n\n"
            f"- **Skill:** {_v(m.get('skill_developed'))}\n"
            f"- **Why now:** {_v(m.get('why_now'))}\n"
            f"- **Success criteria:** {_v(m.get('success_criteria'))}\n"
            f"- **Estimated plan days:** {_v(m.get('estimated_plan_days'))}"
            for i, m in enumerate(roadmap.get("milestones") or [])
        )
        or "_Milestones will appear here._"
    )
    principles = "\n".join(f"- {p}" for p in roadmap.get("learning_principles") or []) or "_No principles yet._"
    adaptations = (
        "\n".join(f"- **{k}:** {v}" for k, v in (roadmap.get("adaptation_rules") or {}).items())
        or "_No scope adjustments yet._"
    )
    overview = "\n\n".join(
        [
            f"**Goal:** {_v(summary.get('goal_outcome'))}",
            f"**Horizon:** {_v(summary.get('goal_horizon'))}",
            f"**Starting level:** {_v(summary.get('starting_level'))}",
            f"**Learning language:** {_v(summary.get('target_language'))}",
            f"**Pace:** {_v(summary.get('pace_description'))} ({_v(summary.get('target_plan_days'))} plan days)",
        ]
    )
    return "\n\n".join(
        [
            "# Roadmap",
            wrap_section("overview", overview),
            "## Milestones",
            wrap_section("milestones", milestones),
            "## Learning principles",
            wrap_section("principles", principles),
            "## Scope adjustments",
            wrap_section("scope_notes", adaptations),
        ]
    )


def seed_four_week_plan_markdown(roadmap: dict) -> str:
    block = roadmap.get("current_block") or {}
    weekly = roadmap.get("weekly_template") or {}
    intro = (
        f"**Current block:** {_v(block.get('focus_summary'))}\n\n"
        f"**Milestone index:** {block.get('milestone_index', 0)} · **Weeks:** {_v(block.get('weeks'))}"
    )
    days = (
        "\n\n".join(
            f"### Day {_v(t.get('block_day'))}\n\n"
            "| Focus | Detail |\n| --- | --- |\n"
            f"| Grammar | {_v(t.get('grammar_focus'))} |\n"
            f"| Vocabulary | {_v(t.get('vocab_theme'))} |\n"
            f"| Goal context | {_v(t.get('goal_context'))} |"
            for t in block.get("themes") or []
        )
        or "_Day-by-day themes will appear here._"
    )
    rhythm = f"{_v(weekly.get('minutes_per_session'))} min per lesson"
    if weekly.get("sessions_per_week"):
        rhythm += f" · {weekly['sessions_per_week']} lessons/week"
    template = (
        f"{rhythm}\n\nEach lesson mixes grammar, vocabulary, review of past mistakes, "
        "and reading/writing for your goal."
    )
    if weekly.get("weekends"):
        template += f"\n\n**Weekends:** {weekly['weekends']}"
    return "\n\n".join(
        [
            "# 4-Week Plan",
            wrap_section("block_overview", intro),
            "## Day-by-day breakdown",
            wrap_section("day_by_day", days),
            "## Weekly template",
            wrap_section("weekly_template", template),
        ]
    )


def blank_progress_markdown() -> str:
    rows = ["Grammar", "Vocabulary", "Reading", "Writing", "Goal-specific"]
    table = "\n".join(
        [
            "| Category | Level | Target | Progress | Weaknesses | Recommendations |",
            "| --- | --- | --- | --- | --- | --- |",
            *(f"| {row} | — | — | — | — | — |" for row in rows),
        ]
    )
    return "\n\n".join(
        [
            "# Progress",
            "## Latest session",
            wrap_section("latest_session", "_Fills in after each accomplished lesson._"),
            "## Skill progress",
            wrap_section("progress_table", table),
            "## Update log",
            wrap_section("update_log", ""),
        ]
    )


def blank_errors_log_markdown() -> str:
    tracker = "| Pattern | Status | Example | Correction |\n| --- | --- | --- | --- |\n| — | — | — | — |"
    confusions = "| Word family / sound-alike | Confusion | Note |\n| --- | --- | --- |\n| — | — | — |"
    return "\n\n".join(
        [
            "# Error Log",
            "## Live pattern tracker",
            wrap_section("pattern_tracker", tracker),
            "## Day-by-day log",
            wrap_section("daily_log", ""),
            "## Word-family / sound-alike confusions",
            wrap_section("confusion_list", confusions),
        ]
    )
