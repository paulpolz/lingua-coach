"""Pydantic models for Gemini structured output.

Unknown keys are ignored. Callers persist ``model_dump()``. LangChain parses
the response; there is no second validation pass after it returns the model.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def normalize_pattern(label: str) -> str:
    """The one canonical form of a mistake label: collapsed whitespace, case-folded, ≤255 chars."""
    return " ".join(label.split()).casefold()[:255]


class _Schema(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Reply(_Schema):
    content: str = Field(min_length=1, description="Learner-facing reply for this turn.")

    @field_validator("content", mode="before")
    @classmethod
    def _strip_content(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


def _strip_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


# --- Lesson curriculum -------------------------------------------------------


class CurriculumSlot(_Schema):
    id: str
    label: str
    exercise_set: str


class InputTask(_Schema):
    type: str
    topic: str
    focus: str


class GoalSpecificTask(_Schema):
    label: str
    format: str


class LessonCurriculum(_Schema):
    lesson_goal: str = Field(description="One sentence.")
    grammar_focus: str = Field(description="The grammar point and why it matters.")
    vocab_theme: str = Field(description="Theme label.")
    milestone_index: int
    slots: list[CurriculumSlot] = Field(min_length=1)
    input_task: InputTask
    goal_specific_task: GoalSpecificTask
    exit_criteria: list[str]
    partner_session: Any | None = Field(
        default=None,
        description="Null. This product has no speaking practice.",
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
    outcome: str | None = None
    horizon: str | None = None
    success_criteria: list[str] | None = None


class LearnerLevel(_Schema):
    self_assessed: str | None = None
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    diagnostic_notes: str | None = None


class TimeBudget(_Schema):
    minutes_per_session: int | None = None
    sessions_per_week: int | None = None
    intensity: str | None = None
    optional_partner_minutes: int | None = None


class LearnerFocus(_Schema):
    skill_priorities: list[str] | None = None
    topic_priorities: list[str] | None = None
    vocab_priorities: list[str] | None = None
    avoid: list[str] | None = None


class PracticePartner(_Schema):
    available: bool | None = None
    minutes: int | None = None
    relationship: str | None = None


class LearnerConstraints(_Schema):
    budget: str | None = None
    practice_partner: PracticePartner | None = None
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


class CourseRoadmapActivity(_Schema):
    id: str
    label: str
    minutes: int


class CourseRoadmapWeeklyTemplate(_Schema):
    minutes_per_session: int
    activities: list[CourseRoadmapActivity]
    partner_session: Any | None = None
    weekends: str | None = None


class CourseRoadmapThemeDay(_Schema):
    block_day: int
    grammar_focus: str | None = None
    vocab_theme: str | None = None
    input_type: str | None = None
    production_focus: str | None = None
    goal_specific_focus: str | None = None


class CourseRoadmapCurrentBlock(_Schema):
    milestone_index: int
    weeks: int | None = None
    focus_summary: str | None = None
    themes: list[CourseRoadmapThemeDay] | None = None


class CourseRoadmap(_Schema):
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
        description=("The full object on a new or revised plan. Null on a clarifying question."),
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


class LessonPlanTask(_Schema):
    id: str
    label: str
    minutes: int


class LessonPlan(_Schema):
    tasks: list[LessonPlanTask] = Field(min_length=1)


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
    completed_task_ids: list[str] = Field(
        default_factory=list,
        description="Ids of tasks marked done this turn.",
    )
    suggest_finish: bool = Field(
        default=False,
        description="Set only when every slot and exit criterion is done.",
    )
    plan_updates: PlanUpdates | None = Field(
        default=None,
        description=(
            "Null unless the learner asks for a concrete plan change. "
            "Then include only the changed fields among goal_summary, level, time_budget, "
            "topics, vocab_priorities, target_plan_days, and grammar_mastery."
        ),
    )
    lesson_plan: LessonPlan | None = Field(
        default=None,
        description="Include on the first coaching turn and when the agenda changes.",
    )
