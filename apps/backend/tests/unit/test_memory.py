"""Stage-1 retrieval: mistake ranking and prior-lesson condensing (pure functions)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.memory import prior_lesson_line, rank_mistakes

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _m(pattern: str, *, due: bool = False, count: int = 1) -> SimpleNamespace:
    review = NOW - timedelta(days=1) if due else NOW + timedelta(days=3)
    return SimpleNamespace(pattern_type=pattern, next_review_at=review, occurrence_count=count)


def test_focus_match_outranks_due_which_outranks_frequency() -> None:
    # Scores: 3 + 0.5, 2 + 0.5, 0.5 * 3.
    mistakes = [_m("articles", count=3), _m("word order", due=True), _m("past simple tense")]
    ranked = rank_mistakes(mistakes, "Past simple for stories", NOW, k=3)  # type: ignore[arg-type]
    assert [m.pattern_type for m in ranked] == ["past simple tense", "word order", "articles"]


def test_rank_keeps_only_k() -> None:
    mistakes = [_m(f"pattern {i}", count=i) for i in range(30)]
    ranked = rank_mistakes(mistakes, "", NOW, k=10)  # type: ignore[arg-type]
    assert len(ranked) == 10
    assert ranked[0].occurrence_count >= 5


def test_never_reviewed_mistake_is_not_due() -> None:
    m = SimpleNamespace(pattern_type="x", next_review_at=None, occurrence_count=1)
    assert rank_mistakes([m], "", NOW, k=1) == [m]  # type: ignore[list-item]


def test_prior_lesson_line_condenses_the_summary() -> None:
    lesson = SimpleNamespace(
        lesson_number=9,
        payload={
            "curriculum": {"grammar_focus": "past simple", "vocab_theme": "travel"},
            "session_summary": {"duration_minutes": 12, "completed_slots": ["warmup"]},
        },
    )
    line = prior_lesson_line(lesson)  # type: ignore[arg-type]
    assert line == 'Lesson 9: grammar "past simple", vocab "travel", 12 min'


def test_prior_lesson_line_tolerates_legacy_summaries() -> None:
    legacy = SimpleNamespace(lesson_number=3, payload={"curriculum": {}, "session_summary": {"duration_minutes": 40}})
    assert prior_lesson_line(legacy) == 'Lesson 3: grammar "?", vocab "?", 40 min'  # type: ignore[arg-type]


def test_snake_case_labels_get_the_focus_bonus() -> None:
    mistakes = [_m("articles", count=3), _m("past_simple_irregular")]
    ranked = rank_mistakes(mistakes, "Past simple irregular verbs", NOW, k=1)  # type: ignore[arg-type]
    assert ranked[0].pattern_type == "past_simple_irregular"


def test_non_latin_labels_still_match() -> None:
    mistakes = [_m("артикли", count=4), _m("прошедшее_время")]
    ranked = rank_mistakes(mistakes, "Прошедшее время глаголов", NOW, k=1)  # type: ignore[arg-type]
    assert ranked[0].pattern_type == "прошедшее_время"
