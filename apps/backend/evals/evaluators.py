"""Deterministic evaluators (refinement-plan Part C). Pure functions, unit-tested.

Each core check takes plain data and returns a score in [0, 1]. `as_langsmith` adapts a
check to LangSmith's `(inputs, outputs, reference_outputs)` evaluator signature. Quality
judgments (pedagogy, tone, "offers a variant after a skip") are LLM-as-judge evaluators
configured in the LangSmith UI, not here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from app.services.report_ops import is_log_section

_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_SPEAKING = re.compile(r"\b(speak(ing)?|pronounc\w*|listen(ing)?|out loud|aloud|voice)\b", re.IGNORECASE)

# Script ranges for non-Latin targets; stopwords for common Latin-script targets.
_SCRIPTS = {
    "ru": r"[Ѐ-ӿ]",
    "uk": r"[Ѐ-ӿ]",
    "el": r"[Ͱ-Ͽ]",
    "ar": r"[؀-ۿ]",
    "he": r"[֐-׿]",
    "ja": r"[぀-ヿ一-鿿]",
    "zh": r"[一-鿿]",
    "ko": r"[가-힯]",
}
_STOPWORDS = {
    "en": {"the", "and", "is", "you", "to", "of", "with", "your", "what", "this"},
    "es": {"el", "la", "que", "y", "es", "de", "con", "tu", "para", "una"},
    "de": {"der", "die", "und", "ist", "du", "nicht", "mit", "ein", "eine", "das"},
    "fr": {"le", "la", "et", "est", "vous", "tu", "de", "avec", "une", "pour"},
    "it": {"il", "la", "che", "e", "di", "con", "una", "per", "sono", "tu"},
    "pt": {"o", "a", "que", "e", "de", "com", "uma", "para", "você", "não"},
}


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def schema_parsed(outputs: dict) -> float:
    return float(outputs.get("parsed") is not None and not outputs.get("error"))


def curriculum_has_no_urls(curriculum: dict) -> float:
    return float(not any(_URL.search(s) for s in _strings(curriculum)))


def curriculum_has_no_speaking(curriculum: dict) -> float:
    """English keywords only: a heuristic for curricula written in English."""
    return float(not any(_SPEAKING.search(s) for s in _strings(curriculum)))


def report_ops_target_existing_sections(ops: list[dict], reports: dict[str, str]) -> float:
    """Every op names an existing section marker, and no op patches an append-only log."""
    for op in ops:
        body = reports.get(op.get("report_type", ""), "")
        if f"<!-- section:{op.get('section_id')} -->" not in body:
            return 0.0
        if op.get("op") == "patch_section" and is_log_section(op["report_type"], op["section_id"]):
            return 0.0
    return 1.0


def reply_language_matches(content: str, target: str) -> float | None:
    """1 if the reply looks written in `target`, 0 if not, None if the language is unsupported."""
    target = target.lower()[:2]
    letters = [c for c in content if c.isalpha()]
    if not letters:
        return 0.0
    if target in _SCRIPTS:
        share = sum(bool(re.match(_SCRIPTS[target], c)) for c in letters) / len(letters)
        return float(share >= 0.5)
    if target in _STOPWORDS:
        words = re.findall(r"\w+", content.lower())
        hits = {lang: sum(w in stops for w in words) for lang, stops in _STOPWORDS.items()}
        return float(max(hits, key=lambda lang: hits[lang]) == target and hits[target] > 0)
    return None


def suggest_finish_respects_time(suggest_finish: bool, active_minutes: int, target_minutes: int) -> float:
    """The tutor should not wrap up before the last minute of the budget."""
    return float(not (suggest_finish and active_minutes < target_minutes - 1))


def correction_spans_in_message(corrections: list[dict], learner_message: str) -> float:
    message = learner_message.lower()
    return float(all(str(c.get("span", "")).lower() in message for c in corrections))


# --- LangSmith adapters --------------------------------------------------------

Evaluator = Callable[[dict, dict, dict], dict]


def _last_user_text(inputs: dict) -> str:
    return next((t["text"] for t in reversed(inputs.get("history", [])) if t["role"] == "user"), "")


def _eval(key: str, check: Callable[[dict, dict], float | None]) -> Evaluator:
    def evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        parsed = outputs.get("parsed")
        score = check(inputs, parsed) if parsed is not None else 0.0
        return {"key": key, "score": score}

    evaluator.__name__ = key
    return evaluator


def _schema(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "schema_parsed", "score": schema_parsed(outputs)}


EVALUATORS: dict[str, list[Evaluator]] = {
    "onboarding_turns": [
        _schema,
        _eval("reply_language", lambda i, p: reply_language_matches(p["content"], i.get("target") or "en")),
    ],
    "lesson_turns": [
        _schema,
        _eval("reply_language", lambda i, p: reply_language_matches(p["content"], i["target"])),
        _eval(
            "suggest_finish_respects_time",
            lambda i, p: suggest_finish_respects_time(p["suggest_finish"], i["active_minutes"], i["target_minutes"]),
        ),
        _eval("correction_spans", lambda i, p: correction_spans_in_message(p["corrections"], _last_user_text(i))),
    ],
    "curriculum_gen": [
        _schema,
        _eval("no_urls", lambda i, p: curriculum_has_no_urls(p)),
        _eval("no_speaking", lambda i, p: curriculum_has_no_speaking(p)),
    ],
    "report_patch": [
        _schema,
        _eval("section_ids_exist", lambda i, p: report_ops_target_existing_sections(p["ops"], i["reports"])),
    ],
}
