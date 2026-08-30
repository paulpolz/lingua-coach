"""lesson_turn_v1 — immersion, correction accuracy, pedagogy, contract."""

from __future__ import annotations

from evals.judges.schema import RubricSpec

RUBRIC_VERSION = "lesson_turn_v1"
DIMENSIONS = ("immersion", "correction_accuracy", "pedagogy", "contract")

SPEC = RubricSpec(
    version=RUBRIC_VERSION,
    dimensions=DIMENSIONS,
    markdown_name="lesson_turn_v1.md",
    title="Lesson chat turn",
)
