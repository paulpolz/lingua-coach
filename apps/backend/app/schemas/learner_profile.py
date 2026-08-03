"""`learner_profile` — structured onboarding-interview output shape from
skills/onboarding_interviewer.md ("Output: learner profile"). Used to parse
and validate the model's structured side-output before persisting to
`profiles` + a draft `learning_goals` row (see database.md).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoalInfo(BaseModel):
    outcome: str
    horizon: str = ""
    success_criteria: list[str] = Field(default_factory=list)


class LevelInfo(BaseModel):
    self_assessed: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    diagnostic_notes: str = ""


class TimeBudgetInfo(BaseModel):
    minutes_per_session: int = 0
    sessions_per_week: int = 0
    optional_partner_minutes: int = 0
    # Free text per the skill file's example ("sustainable" | "intensive"),
    # normalized to the readiness §8 enum (light|moderate|intensive) only at
    # the GET /profile response boundary — see app/api/v1/profile.py.
    intensity: str = ""


class FocusInfo(BaseModel):
    skill_priorities: list[str] = Field(default_factory=list)
    topic_priorities: list[str] = Field(default_factory=list)
    # Not in onboarding_interviewer.md's yaml shape, but readiness §6's
    # GET /profile response needs a `vocab_priorities` list; we ask the model
    # to optionally include it here (see ONBOARDING_EXTRACTION_CONTRACT) and
    # store it inside the existing `focus` JSONB column (additive, no schema
    # change) rather than inventing a new `profiles` column.
    vocab_priorities: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class PracticePartner(BaseModel):
    available: bool = False
    minutes: int = 0
    relationship: str = ""


class ConstraintsInfo(BaseModel):
    budget: str = ""
    practice_partner: PracticePartner | None = None
    learning_style: str = ""


class MotivationInfo(BaseModel):
    why_now: str = ""
    past_blockers: list[str] = Field(default_factory=list)


class LearnerProfile(BaseModel):
    goal: GoalInfo
    level: LevelInfo
    time_budget: TimeBudgetInfo = Field(default_factory=TimeBudgetInfo)
    focus: FocusInfo = Field(default_factory=FocusInfo)
    constraints: ConstraintsInfo = Field(default_factory=ConstraintsInfo)
    motivation: MotivationInfo = Field(default_factory=MotivationInfo)
