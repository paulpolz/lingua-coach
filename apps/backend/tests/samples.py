"""Valid LLM schema instances for tests."""

from __future__ import annotations

from app.schemas.llm import (
    CourseRoadmap,
    CourseRoadmapMilestone,
    CourseRoadmapSummary,
    LessonCurriculum,
)


def curriculum() -> LessonCurriculum:
    return LessonCurriculum(
        lesson_goal="Order a coffee.",
        grammar_focus="Polite requests.",
        vocab_theme="Cafe",
        milestone_index=0,
        new_vocabulary=["latte", "to go", "receipt"],
        review_patterns=[],
        goal_context="Ordering at a cafe while travelling",
        practice_targets=["Writes a short order"],
    )


def roadmap() -> CourseRoadmap:
    return CourseRoadmap(
        version=1,
        summary=CourseRoadmapSummary(
            goal_outcome="Travel",
            goal_horizon="3 months",
            starting_level="A2",
            target_plan_days=30,
        ),
        milestones=[CourseRoadmapMilestone(index=0, title="Basics")],
    )
