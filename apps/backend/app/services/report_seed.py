"""Initial markdown for Roadmap and 4-Week Plan from an accepted course_roadmap."""

from __future__ import annotations

from app.schemas.roadmap import CourseRoadmap
from app.services.report_ops import wrap_section


def seed_roadmap_markdown(roadmap: CourseRoadmap) -> str:
    summary = roadmap.summary
    milestone_lines = []
    for milestone in roadmap.milestones:
        milestone_lines.append(
            f"### {milestone.index + 1}. {milestone.title}\n\n"
            f"- **Skill:** {milestone.skill_developed}\n"
            f"- **Why now:** {milestone.why_now}\n"
            f"- **Success criteria:** {milestone.success_criteria}\n"
            f"- **Estimated plan days:** {milestone.estimated_plan_days}"
        )
    milestones_md = "\n\n".join(milestone_lines) or "_Milestones will appear here._"
    principles = "\n".join(f"- {p}" for p in roadmap.learning_principles) or "_None yet._"
    adaptations = (
        "\n".join(f"- **{k}:** {v}" for k, v in roadmap.adaptation_rules.items())
        or "_No scope adjustments yet._"
    )
    overview_parts = [
        f"**Goal:** {summary.goal_outcome}",
        f"**Horizon:** {summary.goal_horizon}",
        f"**Starting level:** {summary.starting_level}",
    ]
    if summary.target_language:
        overview_parts.append(f"**Learning language:** {summary.target_language}")
    if summary.native_language:
        overview_parts.append(f"**Native language:** {summary.native_language}")
    overview_parts.append(
        f"**Pace:** {summary.pace_description} ({summary.target_plan_days} plan days)"
    )
    overview = "\n\n".join(overview_parts)
    return "\n\n".join(
        [
            "# Roadmap",
            wrap_section("overview", overview),
            "## Milestones",
            wrap_section("milestones", milestones_md),
            "## Learning principles",
            wrap_section("principles", principles),
            "## Scope adjustments",
            wrap_section("scope_notes", adaptations),
        ]
    )


def seed_four_week_plan_markdown(roadmap: CourseRoadmap) -> str:
    block = roadmap.current_block
    intro = (
        f"**Current block:** {block.focus_summary}\n\n"
        f"**Milestone index:** {block.milestone_index} · **Weeks:** {block.weeks}"
    )
    day_lines = []
    for theme in block.themes:
        day_lines.append(
            f"### Day {theme.block_day}\n\n"
            f"| Focus | Detail |\n| --- | --- |\n"
            f"| Grammar | {theme.grammar_focus} |\n"
            f"| Vocabulary | {theme.vocab_theme} |\n"
            f"| Listening / reading | {theme.input_type} |\n"
            f"| Speaking | {theme.production_focus} |\n"
            f"| Writing / interview-prep | {theme.goal_specific_focus} |"
        )
    days_md = "\n\n".join(day_lines) or "_Day-by-day themes will appear here._"
    weekly = roadmap.weekly_template
    activities = "\n".join(
        f"- {a.label}: {a.minutes} min" for a in weekly.activities
    ) or "_No weekly template yet._"
    return "\n\n".join(
        [
            "# 4-Week Plan",
            wrap_section("block_overview", intro),
            "## Day-by-day breakdown",
            wrap_section("day_by_day", days_md),
            "## Weekly template",
            wrap_section("weekly_template", f"{weekly.minutes_per_session} min sessions\n\n{activities}"),
        ]
    )


def blank_progress_markdown() -> str:
    table = (
        "| Category | Level | Target | Progress | Weaknesses | Recommendations |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Grammar | — | — | — | — | — |\n"
        "| Vocabulary | — | — | — | — | — |\n"
        "| Listening | — | — | — | — | — |\n"
        "| Speaking | — | — | — | — | — |\n"
        "| Writing | — | — | — | — | — |\n"
        "| Interview readiness | — | — | — | — | — |"
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
    tracker = (
        "| Pattern | Status | Example | Correction |\n"
        "| --- | --- | --- | --- |\n"
        "| — | — | — | — |"
    )
    confusions = (
        "| Word family / sound-alike | Confusion | Note |\n"
        "| --- | --- | --- |\n"
        "| — | — | — |"
    )
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
