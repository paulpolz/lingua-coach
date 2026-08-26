"""`course_roadmap` v1 — canonical shape from docs/tech_requirements/database.md
and skills/course_composer.md. Validated on `POST /onboarding/accept` and when
parsing the model's structured side-output during onboarding chat.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RoadmapSummary(BaseModel):
    goal_outcome: str
    goal_horizon: str
    starting_level: str
    target_language: str | None = None
    native_language: str | None = None
    target_plan_days: int = Field(gt=0)
    target_plan_days_range: list[int] = Field(min_length=2, max_length=2)
    pace_description: str


class RoadmapMilestone(BaseModel):
    index: int
    title: str
    skill_developed: str
    why_now: str
    connects_to: list[int] = Field(default_factory=list)
    success_criteria: str
    estimated_plan_days: int = Field(gt=0)


class WeeklyActivity(BaseModel):
    id: str
    label: str
    minutes: int = Field(ge=0)


class PartnerSessionPhase(BaseModel):
    id: str
    minutes: int = Field(ge=0)


class PartnerSession(BaseModel):
    minutes: int = Field(ge=0)
    phases: list[PartnerSessionPhase] = Field(default_factory=list)


class WeeklyTemplate(BaseModel):
    minutes_per_session: int = Field(gt=0)
    activities: list[WeeklyActivity]
    partner_session: PartnerSession | None = None
    weekends: str


class CurrentBlockTheme(BaseModel):
    block_day: int
    grammar_focus: str
    vocab_theme: str
    input_type: str
    production_focus: str
    goal_specific_focus: str


class CurrentBlock(BaseModel):
    milestone_index: int
    weeks: int = Field(gt=0)
    focus_summary: str
    themes: list[CurrentBlockTheme] = Field(default_factory=list)


class CourseRoadmap(BaseModel):
    version: int = 1
    summary: RoadmapSummary
    milestones: list[RoadmapMilestone] = Field(min_length=1)
    weekly_template: WeeklyTemplate
    current_block: CurrentBlock
    learning_principles: list[str] = Field(default_factory=list)
    # Fixed-key object in database.md's example, but treated as an open map
    # here since the model may phrase additional adaptation signals — the
    # four illustrative keys are pedagogy content, not a hard schema.
    adaptation_rules: dict[str, str] = Field(default_factory=dict)
    current_milestone_index: int = 0

    @field_validator("version")
    @classmethod
    def _version_must_be_1(cls, value: int) -> int:
        if value != 1:
            raise ValueError("course_roadmap version must be 1")
        return value
