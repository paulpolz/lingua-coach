"""lesson_generation_v1 — groundedness, difficulty, immersion (not schema)."""

from __future__ import annotations

from evals.judges.schema import RubricSpec

RUBRIC_VERSION = "lesson_generation_v1"
DIMENSIONS = ("groundedness", "difficulty", "immersion")

SPEC = RubricSpec(
    version=RUBRIC_VERSION,
    dimensions=DIMENSIONS,
    markdown_name="lesson_generation_v1.md",
    title="Lesson curriculum",
)
