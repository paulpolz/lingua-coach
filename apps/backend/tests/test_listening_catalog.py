from __future__ import annotations

from pathlib import Path

from app.services.listening_catalog import (
    InputAssignment,
    apply_input_assignment,
    assign_input,
    decide_input_mode,
    load_clips,
    parse_cefr_band,
    prior_resource_ids,
    select_clip,
)
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LESSON_CURRICULUM

_CONTENT = str(Path(__file__).resolve().parents[3] / "content")


def test_catalog_loads_five_languages() -> None:
    clips = load_clips(_CONTENT)
    langs = {clip.language for clip in clips}
    assert langs == {"en", "de", "fr", "es", "it"}
    assert len(clips) >= 30
    assert all(clip.notice_points and clip.url.startswith("http") for clip in clips)


def test_parse_cefr_band() -> None:
    assert parse_cefr_band("A2") == ("A2",)
    assert parse_cefr_band("around b1") == ("B1",)
    assert parse_cefr_band("beginner") == ("A1", "A2")
    assert parse_cefr_band("intermediate") == ("B1",)
    assert parse_cefr_band(None) == ("A2",)
    assert parse_cefr_band("pretty good") == ("A2",)


def test_decide_input_mode_uses_theme_then_odd_even() -> None:
    assert decide_input_mode(roadmap=VALID_COURSE_ROADMAP, lesson_number=1) == "listening"
    reading_map = {
        "current_block": {"themes": [{"block_day": 2, "input_type": "reading"}]}
    }
    assert decide_input_mode(roadmap=reading_map, lesson_number=2) == "reading"
    assert decide_input_mode(roadmap={}, lesson_number=1) == "listening"
    assert decide_input_mode(roadmap={}, lesson_number=2) == "reading"


def test_select_clip_filters_language_and_prefers_topic() -> None:
    clips = load_clips(_CONTENT)
    hotel = select_clip(
        language="es",
        level="A2",
        haystack="hotel reserva habitación viaje",
        clips=clips,
    )
    assert hotel is not None
    assert hotel.language == "es"
    assert "travel" in hotel.topics or "daily_life" in hotel.topics


def test_no_match_language_returns_none() -> None:
    clips = load_clips(_CONTENT)
    assert (
        select_clip(language="ja", level="A2", haystack="travel", clips=clips) is None
    )


def test_assign_input_downgrades_when_no_clip() -> None:
    assignment = assign_input(
        language="ja",
        level="A2",
        lesson_number=1,
        roadmap={"current_block": {"themes": [{"block_day": 1, "input_type": "listening"}]}},
        extra_haystack="travel",
        clips=load_clips(_CONTENT),
    )
    assert assignment.mode == "reading"
    assert assignment.clip is None


def test_de_dupe_skips_used_ids() -> None:
    clips = load_clips(_CONTENT)
    first = select_clip(language="es", level="A2", haystack="hotel", clips=clips)
    assert first is not None
    second = select_clip(
        language="es",
        level="A2",
        haystack="hotel",
        used_ids={first.id},
        clips=clips,
    )
    assert second is not None
    assert second.id != first.id


def test_select_clip_no_band_match_returns_none() -> None:
    clips = load_clips(_CONTENT)
    sample = next(clip for clip in clips if clip.language == "es")
    only_c1 = sample.model_copy(update={"cefr": ["C1"]})
    assert (
        select_clip(language="es", level="A2", haystack="travel", clips=(only_c1,))
        is None
    )


def test_assign_input_downgrades_when_band_empty() -> None:
    clips = load_clips(_CONTENT)
    sample = next(clip for clip in clips if clip.language == "es")
    only_c1 = sample.model_copy(update={"cefr": ["C1"]})
    assignment = assign_input(
        language="es",
        level="A2",
        lesson_number=1,
        roadmap={"current_block": {"themes": [{"block_day": 1, "input_type": "listening"}]}},
        extra_haystack="travel",
        clips=(only_c1,),
    )
    assert assignment.mode == "reading"
    assert assignment.clip is None


def test_prior_resource_ids_last_five() -> None:
    prior = [
        {
            "lesson_number": i,
            "curriculum": {"input_task": {"resource": {"id": f"id-{i}"}}},
        }
        for i in range(1, 8)
    ]
    assert prior_resource_ids(prior) == {f"id-{i}" for i in range(3, 8)}


def test_prior_resource_ids() -> None:
    prior = [
        {
            "curriculum": {
                "input_task": {"resource": {"id": "es-notes-beginners-hotel-a2"}}
            }
        }
    ]
    assert prior_resource_ids(prior) == {"es-notes-beginners-hotel-a2"}


def test_apply_input_assignment_overwrites_fake_url_and_speaking_slot() -> None:
    clips = load_clips(_CONTENT)
    clip = select_clip(language="en", level="B1", haystack="work meeting", clips=clips)
    assert clip is not None

    raw = {
        "input_task": {
            "type": "listening",
            "topic": "x",
            "focus": "y",
            "resource": {
                "id": "invented",
                "kind": "video",
                "title": "Fake",
                "url": "https://www.youtube.com/watch?v=dQw4w9wgGcQ",
                "duration_sec": 10,
                "source": "nope",
                "captions": "none",
                "synopsis": "nope",
                "notice_points": ["nope"],
            },
        },
        "slots": [
            {"id": "speaking", "label": "Oral", "exercise_set": "Talk"},
            {"id": "writing", "label": "Email", "exercise_set": "Write"},
        ],
    }
    out = apply_input_assignment(raw, InputAssignment(mode="listening", clip=clip))
    assert out["input_task"]["resource"]["id"] == clip.id
    assert out["input_task"]["resource"]["url"] == clip.url
    assert [s["id"] for s in out["slots"]] == ["writing"]


def test_apply_reading_strips_resource() -> None:
    out = apply_input_assignment(
        VALID_LESSON_CURRICULUM, InputAssignment(mode="reading")
    )
    assert out["input_task"]["type"] == "reading"
    assert "resource" not in out["input_task"]
