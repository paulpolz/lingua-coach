"""Stage-1 retrieval (docs/tech_requirements/rag.md): pick the learner memory that fits
this call instead of sending everything. Plain SQL and Python; no embeddings.

Stage 2 (pgvector) is deferred until evals show stage 1 missing relevant history.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from app.models.lesson import Lesson
from app.models.mistake import Mistake

CHAT_MISTAKES = 10
GENERATION_MISTAKES = 15
FULL_PRIOR_LESSONS = 2
CONDENSED_PRIOR_LESSONS = 3

# Letters and digits only, so snake_case and kebab-case labels split into words.
_WORD = re.compile(r"[^\W_]{4,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def rank_mistakes(mistakes: Sequence[Mistake], focus_text: str, now: datetime, k: int) -> list[Mistake]:
    """score = 3·(shares a word with the focus) + 2·(review due) + 0.5·min(count, 5)."""
    focus = _words(focus_text)

    def score(m: Mistake) -> float:
        due = m.next_review_at is not None and m.next_review_at <= now
        return 3 * bool(_words(m.pattern_type) & focus) + 2 * due + 0.5 * min(m.occurrence_count, 5)

    return sorted(mistakes, key=score, reverse=True)[:k]


def prior_lesson_line(lesson: Lesson) -> str:
    """One line per older lesson: `Lesson 9: grammar "x", vocab "y", 12 min`."""
    payload = lesson.payload or {}
    curriculum = payload.get("curriculum") or {}
    summary = payload.get("session_summary") or {}
    parts = [
        f'Lesson {lesson.lesson_number}: grammar "{curriculum.get("grammar_focus") or "?"}"',
        f'vocab "{curriculum.get("vocab_theme") or "?"}"',
    ]
    if summary.get("duration_minutes") is not None:
        parts.append(f"{summary['duration_minutes']} min")
    return ", ".join(parts)
