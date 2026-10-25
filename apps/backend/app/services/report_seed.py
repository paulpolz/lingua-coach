"""Initial markdown for the four coach reports."""

from __future__ import annotations

from app.services.report_ops import wrap_section


def seed_roadmap_markdown(roadmap: dict) -> str:
    summary = roadmap.get("summary") or {}
    milestones = "\n\n".join(
        f"### {m.get('index', i) + 1}. {m.get('title', '')}\n\n"
        f"- **Skill:** {m.get('skill_developed', '')}\n"
        f"- **Why now:** {m.get('why_now', '')}\n"
        f"- **Success criteria:** {m.get('success_criteria', '')}\n"
        f"- **Estimated plan days:** {m.get('estimated_plan_days', '')}"
        for i, m in enumerate(roadmap.get("milestones") or [])
    ) or "_Milestones will appear here._"
    principles = "\n".join(f"- {p}" for p in roadmap.get("learning_principles") or []) or "_None yet._"
    adaptations = "\n".join(
        f"- **{k}:** {v}" for k, v in (roadmap.get("adaptation_rules") or {}).items()
    ) or "_No scope adjustments yet._"
    overview = "\n\n".join(
        [
            f"**Goal:** {summary.get('goal_outcome', '')}",
            f"**Horizon:** {summary.get('goal_horizon', '')}",
            f"**Starting level:** {summary.get('starting_level', '')}",
            f"**Learning language:** {summary.get('target_language', '')}",
            f"**Pace:** {summary.get('pace_description', '')} ({summary.get('target_plan_days', '?')} plan days)",
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
        f"**Current block:** {block.get('focus_summary', '')}\n\n"
        f"**Milestone index:** {block.get('milestone_index', 0)} · **Weeks:** {block.get('weeks', '')}"
    )
    days = "\n\n".join(
        f"### Day {t.get('block_day', '')}\n\n"
        "| Focus | Detail |\n| --- | --- |\n"
        f"| Grammar | {t.get('grammar_focus', '')} |\n"
        f"| Vocabulary | {t.get('vocab_theme', '')} |\n"
        f"| Reading | {t.get('input_type', 'reading')} |\n"
        f"| Writing | {t.get('production_focus', '')} |\n"
        f"| Goal-specific | {t.get('goal_specific_focus', '')} |"
        for t in block.get("themes") or []
    ) or "_Day-by-day themes will appear here._"
    activities = "\n".join(
        f"- {a.get('label', '')}: {a.get('minutes', '')} min" for a in weekly.get("activities") or []
    ) or "_No weekly template yet._"
    return "\n\n".join(
        [
            "# 4-Week Plan",
            wrap_section("block_overview", intro),
            "## Day-by-day breakdown",
            wrap_section("day_by_day", days),
            "## Weekly template",
            wrap_section(
                "weekly_template", f"{weekly.get('minutes_per_session', '?')} min sessions\n\n{activities}"
            ),
        ]
    )


def blank_progress_markdown() -> str:
    rows = ["Grammar", "Vocabulary", "Listening", "Reading", "Writing", "Goal-specific"]
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
