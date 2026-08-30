"""onboarding_v1 — completeness, one-question rule, roadmap honesty."""

from __future__ import annotations

from evals.judges.schema import RubricSpec

RUBRIC_VERSION = "onboarding_v1"
DIMENSIONS = ("completeness", "one_question_rule", "roadmap_honesty")

SPEC = RubricSpec(
    version=RUBRIC_VERSION,
    dimensions=DIMENSIONS,
    markdown_name="onboarding_v1.md",
    title="Onboarding interview / handoff",
)
