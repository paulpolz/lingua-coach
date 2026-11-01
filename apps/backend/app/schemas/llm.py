"""Pydantic models for Gemini structured output.

Unknown keys are ignored. Callers persist ``model_dump()``. LangChain parses
the response; there is no second validation pass after it returns the model.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, field_validator

LESSON_MINUTES_RANGE = (5, 180)


def normalize_pattern(label: str) -> str:
    """The one canonical form of a mistake label: collapsed whitespace, case-folded, ≤255 chars."""
    return " ".join(label.split()).casefold()[:255]


def _lesson_minutes_or_none(value: object) -> object:
    # The model echoes what the learner said. Rejecting "3 minutes" would fail the whole turn
    # (a 502 on every retry); unknown makes the interviewer ask again. PATCH /profile and
    # accept keep the hard bound.
    if isinstance(value, int) and not isinstance(value, bool):
        low, high = LESSON_MINUTES_RANGE
        return value if low <= value <= high else None
    return value


class _Schema(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _strip_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class _Reply(_Schema):
    content: str = Field(min_length=1, description="Learner-facing reply for this turn.")

    @field_validator("content", mode="before")
    @classmethod
    def _strip_content(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


# --- Lesson curriculum -------------------------------------------------------


class LessonCurriculum(_Schema):
    """One timed lesson of mixed chat practice. The backend stores `target_minutes` beside it."""

    lesson_goal: str = Field(description="One sentence: what the learner can do after this lesson.")
    grammar_focus: str = Field(description="One grammar point and why it matters for the learner's goal.")
    vocab_theme: str = Field(description="Theme label for today's words.")
    milestone_index: int
    new_vocabulary: list[str] = Field(
        description=(
            "Words or phrases to teach today, in the target language: about 3-4 for a 10-minute lesson, "
            "6-10 for 30 minutes or more. Later lessons review them."
        )
    )
    review_patterns: list[str] = Field(
        description="pattern_type values of due mistakes to retest today, copied exactly. Empty if none are due."
    )
    goal_context: str = Field(
        description="The real reading/writing situation from the learner's goal used today, e.g. 'a status email'."
    )
    practice_targets: list[str] = Field(
        description="2-4 observable things to get right today. Used for praise and checks, not to end the lesson."
    )


# --- Report patch ------------------------------------------------------------


class ReportOp(_Schema):
    report_type: Literal["progress", "errors_log", "roadmap", "four_week_plan"]
    op: Literal["append_entry", "patch_section"] = Field(
        description=(
            "append_entry adds a dated log entry; patch_section replaces the section. "
            "Log sections (update_log, daily_log) accept append_entry only."
        )
    )
    section_id: str = Field(description="Must match an existing <!-- section:ID --> marker.")
    markdown: str


class ReportPatch(_Schema):
    ops: list[ReportOp] = Field(default_factory=list, description="May be empty.")


# --- Learner profile ---------------------------------------------------------


class LearnerLanguages(_Schema):
    native: str = Field(min_length=1)
    target: str = Field(min_length=1)

    @field_validator("native", "target", mode="before")
    @classmethod
    def _strip_language(cls, value: object) -> object:
        return _strip_string(value)


class LearnerGoal(_Schema):
    outcome: str | None = Field(default=None, description="A concrete real-world outcome.")
    horizon: str | None = None
    success_criteria: list[str] | None = Field(default=None, description="Observable behaviors, not CEFR labels alone.")


class LearnerLevel(_Schema):
    self_assessed: str | None = None
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    diagnostic_notes: str | None = None


class TimeBudget(_Schema):
    minutes_per_session: Annotated[int | None, BeforeValidator(_lesson_minutes_or_none)] = Field(
        default=None,
        description=(
            "Length of one lesson in minutes (5-180); every lesson is timed to this. "
            "Required before a roadmap is drafted."
        ),
    )
    sessions_per_week: int | None = None
    intensity: str | None = None


class LearnerFocus(_Schema):
    skill_priorities: list[str] | None = None
    topic_priorities: list[str] | None = None
    vocab_priorities: list[str] | None = None
    avoid: list[str] | None = None


class LearnerConstraints(_Schema):
    budget: str | None = None
    learning_style: str | None = None


class LearnerMotivation(_Schema):
    why_now: str | None = None
    past_blockers: list[str] | None = None


class LearnerProfile(_Schema):
    languages: LearnerLanguages
    goal: LearnerGoal | None = None
    level: LearnerLevel | None = None
    time_budget: TimeBudget | None = None
    focus: LearnerFocus | None = None
    constraints: LearnerConstraints | None = None
    motivation: LearnerMotivation | None = None


# --- Course roadmap ----------------------------------------------------------


class CourseRoadmapSummary(_Schema):
    goal_outcome: str
    goal_horizon: str
    starting_level: str
    target_plan_days: int
    target_plan_days_range: list[int] | None = None
    pace_description: str | None = None
    target_language: str | None = None
    native_language: str | None = None
    languages: LearnerLanguages | None = None

    @field_validator("target_plan_days_range")
    @classmethod
    def _two_day_range(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(value) != 2:
            raise ValueError("target_plan_days_range must be two integers")
        return value


class CourseRoadmapMilestone(_Schema):
    index: int
    title: str
    skill_developed: str | None = None
    why_now: str | None = None
    connects_to: list[int] | None = None
    success_criteria: str | None = None
    estimated_plan_days: int | None = None


class CourseRoadmapWeeklyTemplate(_Schema):
    """Every lesson is `minutes_per_session` of mixed chat practice; there is no activity split."""

    minutes_per_session: int = Field(description="The learner's lesson length in minutes.")
    sessions_per_week: int | None = None
    weekends: str | None = None


class CourseRoadmapThemeDay(_Schema):
    block_day: int
    grammar_focus: str | None = None
    vocab_theme: str | None = None
    goal_context: str | None = Field(default=None, description="The goal situation practiced in reading/writing.")


class CourseRoadmapCurrentBlock(_Schema):
    milestone_index: int
    weeks: int | None = None
    focus_summary: str | None = None
    themes: list[CourseRoadmapThemeDay] | None = Field(
        default=None, description="First 1-4 weeks. Themes only: no word lists, exercises or URLs."
    )


class CourseRoadmap(_Schema):
    """String values are in the learning language; keys stay English."""

    version: int
    summary: CourseRoadmapSummary
    milestones: list[CourseRoadmapMilestone] = Field(min_length=1)
    weekly_template: CourseRoadmapWeeklyTemplate | None = None
    current_block: CourseRoadmapCurrentBlock | None = None
    learning_principles: list[str] | None = None
    adaptation_rules: dict[str, str] | None = None
    current_milestone_index: int | None = None


class OnboardingReply(_Reply):
    learner_profile: LearnerProfile | None = Field(
        default=None,
        description="Include only once both languages are known, and again when they change.",
    )
    course_roadmap: CourseRoadmap | None = Field(
        default=None,
        description=(
            "The full object on a new or revised plan; null on a clarifying question. "
            "String values in the learning language, keys in English."
        ),
    )


# --- Lesson chat -------------------------------------------------------------


class Correction(_Schema):
    span: str
    correction: str
    type: str
    note: str | None = None


class MistakeEntry(_Schema):
    pattern_type: Annotated[str, BeforeValidator(_strip_string), AfterValidator(normalize_pattern)] = Field(
        min_length=1, description="Short stable label for a recurring error, e.g. 'missing articles'."
    )
    example_text: str
    correction: str


class PracticeResult(_Schema):
    aspect: Literal["grammar", "vocabulary", "review"]
    item: str = Field(
        description="review: the mistake pattern_type exactly as listed; grammar: the point; vocabulary: the word."
    )
    result: Literal["solid", "shaky"] = Field(
        description="solid: done correctly, ideally without help; shaky: wrong or needed help."
    )


class PlanUpdates(_Schema):
    goal_summary: str | None = None
    level: str | None = None
    time_budget: TimeBudget | None = None
    topics: list[str] | None = None
    vocab_priorities: list[str] | None = None
    target_plan_days: int | None = None
    grammar_mastery: dict[str, Any] | None = None


class LessonReply(_Reply):
    corrections: list[Correction] = Field(
        default_factory=list,
        description="Corrections for this turn only.",
    )
    tips: list[str] = Field(default_factory=list, description="Tips for this turn only.")
    mistakes: list[MistakeEntry] = Field(
        default_factory=list,
        description="One entry per recurring error pattern.",
    )
    practiced: list[PracticeResult] = Field(
        default_factory=list,
        description="Items the learner practiced this turn and how it went.",
    )
    suggest_finish: bool = Field(
        default=False,
        description="True only in the closing recap, once the Time line shows the time budget is used.",
    )
    plan_updates: PlanUpdates | None = Field(
        default=None,
        description=(
            "Null unless the learner asks for a concrete plan change. "
            "Then include only the changed fields among goal_summary, level, time_budget, "
            "topics, vocab_priorities, target_plan_days, and grammar_mastery."
        ),
    )
