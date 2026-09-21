"""Curated listening clips for lesson input days.

Catalog YAML lives in repo `content/listening/`. The generation job picks
one clip (or downgrades to reading). Gemini never invents URLs.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.config import settings

CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")
_CEFR_TOKEN = re.compile(r"\b([ABC][12])\b", re.IGNORECASE)

InputMode = Literal["listening", "reading"]
MappingLike = dict[str, Any]

_LEVEL_ALIASES: dict[str, tuple[str, ...]] = {
    "beginner": ("A1", "A2"),
    "elementary": ("A2",),
    "pre-intermediate": ("A2", "B1"),
    "preintermediate": ("A2", "B1"),
    "intermediate": ("B1",),
    "upper-intermediate": ("B2",),
    "upper intermediate": ("B2",),
    "advanced": ("C1", "C2"),
}

_TOPIC_EXTRAS: dict[str, tuple[str, ...]] = {
    "travel": (
        "hotel",
        "viaje",
        "train",
        "tren",
        "reise",
        "voyage",
        "viaggio",
        "habitación",
        "airport",
    ),
    "food": ("food", "comida", "restaurant", "essen", "repas", "cibo", "café"),
    "work": ("work", "trabajo", "meeting", "büro", "travail", "lavoro", "budget"),
    "city": ("city", "ciudad", "stadt", "ville", "città", "street"),
    "news": ("news", "nachrichten", "noticias", "journal", "notizie"),
    "culture": ("culture", "kultur", "cultura"),
    "daily_life": ("daily", "alltag", "quotidien", "cotidiano", "giorno"),
}


class CatalogClip(BaseModel):
    id: str
    language: str
    cefr: list[str] = Field(min_length=1)
    kind: Literal["video", "audio"]
    duration_sec: int = Field(gt=0)
    title: str
    url: str
    source: str
    topics: list[str] = Field(default_factory=list)
    captions: Literal["target", "dual", "none"]
    license: Literal["public_domain", "cc_by", "link_only"]
    synopsis: str
    notice_points: list[str] = Field(min_length=1)

    def to_resource_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "duration_sec": self.duration_sec,
            "source": self.source,
            "captions": self.captions,
            "synopsis": self.synopsis.strip(),
            "notice_points": list(self.notice_points),
        }


@dataclass(frozen=True)
class InputAssignment:
    mode: InputMode
    clip: CatalogClip | None = None

    def prompt_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.clip is not None:
            payload["resource"] = self.clip.to_resource_dict()
        return payload


def _content_dir() -> Path:
    return Path(settings.content_dir)


@functools.lru_cache(maxsize=None)
def load_clips(content_dir: str | None = None) -> tuple[CatalogClip, ...]:
    root = Path(content_dir) if content_dir else _content_dir()
    path = root / "listening" / "catalog.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read listening catalog at {path}: {exc}") from exc
    items = (raw or {}).get("clips") or []
    clips: list[CatalogClip] = []
    for item in items:
        try:
            clips.append(CatalogClip.model_validate(item))
        except ValidationError as exc:
            raise RuntimeError(f"Invalid listening catalog row in {path}: {exc}") from exc
    return tuple(clips)


def parse_cefr_band(level: str | None) -> tuple[str, ...]:
    """Map `profiles.target_level` free text to one or more CEFR bands.

    Unknown values default to A2.
    """
    if not level or not str(level).strip():
        return ("A2",)
    text = str(level).strip()
    token = _CEFR_TOKEN.search(text)
    if token:
        return (token.group(1).upper(),)
    lowered = text.lower()
    for alias, bands in _LEVEL_ALIASES.items():
        if alias in lowered:
            return bands
    return ("A2",)


def _theme_for_lesson(roadmap: MappingLike, lesson_number: int) -> dict[str, Any] | None:
    block = roadmap.get("current_block") or {} if isinstance(roadmap, dict) else {}
    themes = block.get("themes") if isinstance(block, dict) else None
    if not isinstance(themes, list) or not themes:
        return None
    dict_themes = [t for t in themes if isinstance(t, dict)]
    if not dict_themes:
        return None
    for theme in dict_themes:
        if theme.get("block_day") == lesson_number:
            return theme
    return dict_themes[(max(lesson_number, 1) - 1) % len(dict_themes)]


def decide_input_mode(*, roadmap: MappingLike | None, lesson_number: int) -> InputMode:
    theme = _theme_for_lesson(roadmap or {}, lesson_number)
    raw = (theme or {}).get("input_type") if theme else None
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered == "listening":
            return "listening"
        if lowered == "reading":
            return "reading"
    return "listening" if lesson_number % 2 == 1 else "reading"


def _haystack(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            chunks.extend(str(v) for v in part.values() if isinstance(v, (str, list)))
            for value in part.values():
                if isinstance(value, list):
                    chunks.extend(str(item) for item in value)
        elif isinstance(part, (list, tuple)):
            chunks.extend(str(v) for v in part if isinstance(v, (str, int)))
    return " ".join(chunks).lower()


def _topic_score(clip: CatalogClip, haystack: str) -> int:
    score = 0
    for tag in clip.topics:
        needle = tag.replace("_", " ")
        if needle in haystack or tag in haystack:
            score += 3
        stem = tag.split("_")[0]
        if stem and stem in haystack:
            score += 1
        for word in _TOPIC_EXTRAS.get(tag, ()):
            if word in haystack:
                score += 2
    return score


def _clip_rank(clip: CatalogClip, haystack: str) -> tuple[int, int, int]:
    topic = _topic_score(clip, haystack)
    duration_bonus = 1 if clip.duration_sec <= 720 else 0
    caption_bonus = 0 if clip.captions == "none" else 1
    return (topic, duration_bonus, caption_bonus)


def select_clip(
    *,
    language: str | None,
    level: str | None,
    haystack: str,
    used_ids: set[str] | frozenset[str] = frozenset(),
    clips: tuple[CatalogClip, ...] | None = None,
) -> CatalogClip | None:
    from app.services.languages import normalize_language

    if not language or not str(language).strip():
        return None
    code = normalize_language(str(language))
    band = set(parse_cefr_band(level))
    pool = clips if clips is not None else load_clips()
    eligible = [
        clip
        for clip in pool
        if clip.language == code
        and clip.id not in used_ids
        and band.intersection({c.upper() for c in clip.cefr})
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda clip: _clip_rank(clip, haystack), reverse=True)
    return eligible[0]


def prior_resource_ids(prior_lessons: list[Any] | None) -> set[str]:
    """Clip ids from the last 5 prior lessons (newest first when numbered)."""
    items = [row for row in (prior_lessons or []) if isinstance(row, dict)]
    if any(isinstance(row.get("lesson_number"), int) for row in items):
        items = sorted(
            items,
            key=lambda row: row.get("lesson_number")
            if isinstance(row.get("lesson_number"), int)
            else -1,
            reverse=True,
        )
    ids: set[str] = set()
    for lesson in items[:5]:
        curriculum = lesson.get("curriculum") or lesson
        if not isinstance(curriculum, dict):
            continue
        resource = (curriculum.get("input_task") or {}).get("resource") or {}
        if isinstance(resource, dict) and resource.get("id"):
            ids.add(str(resource["id"]))
    return ids


def assign_input(
    *,
    language: str | None,
    level: str | None,
    lesson_number: int,
    roadmap: MappingLike | None,
    vocab_theme: str | None = None,
    extra_haystack: str = "",
    prior_lessons: list[Any] | None = None,
    clips: tuple[CatalogClip, ...] | None = None,
) -> InputAssignment:
    mode = decide_input_mode(roadmap=roadmap, lesson_number=lesson_number)
    if mode == "reading":
        return InputAssignment(mode="reading")
    theme = _theme_for_lesson(roadmap or {}, lesson_number) or {}
    haystack = _haystack(
        vocab_theme,
        extra_haystack,
        theme.get("vocab_theme"),
        theme.get("grammar_focus"),
        theme.get("production_focus"),
        theme.get("goal_specific_focus"),
    )
    clip = select_clip(
        language=language,
        level=level,
        haystack=haystack,
        used_ids=prior_resource_ids(prior_lessons),
        clips=clips,
    )
    if clip is None:
        return InputAssignment(mode="reading")
    return InputAssignment(mode="listening", clip=clip)


def apply_input_assignment(
    curriculum: dict[str, Any], assignment: InputAssignment
) -> dict[str, Any]:
    """Overwrite input_task type/resource from the server assignment.

    Also maps leftover `speaking` slot ids to `writing` so old roadmaps do
    not keep an oral task id on the persisted curriculum.
    """
    data = dict(curriculum)
    input_task = dict(data.get("input_task") or {})
    if assignment.mode == "listening" and assignment.clip is not None:
        input_task["type"] = "listening"
        input_task["resource"] = assignment.clip.to_resource_dict()
        if not str(input_task.get("topic") or "").strip():
            input_task["topic"] = assignment.clip.title
        if not str(input_task.get("focus") or "").strip():
            input_task["focus"] = "; ".join(assignment.clip.notice_points[:3])
    else:
        input_task["type"] = "reading"
        input_task.pop("resource", None)
        input_task.setdefault("topic", input_task.get("topic") or "")
        input_task.setdefault("focus", input_task.get("focus") or "")
    data["input_task"] = input_task

    slots = data.get("slots")
    if isinstance(slots, list):
        remapped: list[Any] = []
        seen_writing = any(isinstance(slot, dict) and slot.get("id") == "writing" for slot in slots)
        for slot in slots:
            if not isinstance(slot, dict):
                remapped.append(slot)
                continue
            if slot.get("id") == "speaking":
                if seen_writing:
                    continue
                slot = {**slot, "id": "writing"}
                seen_writing = True
            remapped.append(slot)
        data["slots"] = remapped
    return data


def assignment_from_generation_context(context: dict[str, Any]) -> InputAssignment:
    profile = context.get("learner_profile") or {}
    plan = context.get("active_plan") or {}
    roadmap = plan.get("roadmap") if isinstance(plan, dict) else None
    lesson_number = int(context.get("lesson_number") or 1)
    prior = context.get("prior_lessons") or []
    return assign_input(
        language=profile.get("target_language") if isinstance(profile, dict) else None,
        level=profile.get("target_level") if isinstance(profile, dict) else None,
        lesson_number=lesson_number,
        roadmap=roadmap if isinstance(roadmap, dict) else None,
        extra_haystack=_haystack(
            profile.get("focus") if isinstance(profile, dict) else None,
            profile.get("goal_outcome") if isinstance(profile, dict) else None,
        ),
        prior_lessons=prior if isinstance(prior, list) else None,
    )


def enrich_generation_context(context: dict[str, Any]) -> dict[str, Any]:
    """Add `input_assignment` for the generation prompt. Does not mutate input."""
    enriched = dict(context)
    assignment = assignment_from_generation_context(enriched)
    enriched["input_assignment"] = assignment.prompt_dict()
    return enriched
