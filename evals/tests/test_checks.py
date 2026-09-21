from evals.checks import CheckContext, check_catalog_url_used

_URL = "https://www.notesinspanish.com/beginners-spanish-audio/"
_FIXTURE = {
    "curriculum": {
        "lesson_goal": "Reservar una habitación",
        "grammar_focus": "Artículos",
        "vocab_theme": "Hotel",
        "slots": [{"id": "warmup", "label": "Recuerdo", "exercise_set": "Tres frases"}],
        "input_task": {
            "type": "listening",
            "topic": "Hotel",
            "focus": "Artículos",
            "resource": {
                "id": "es-notes-beginners-hotel-a2",
                "kind": "audio",
                "title": "Audio de hotel",
                "url": _URL,
                "duration_sec": 480,
                "source": "Notes in Spanish",
                "captions": "none",
                "synopsis": "Llegar a un hotel.",
                "notice_points": ["artículos"],
            },
        },
        "goal_specific_task": {"label": "Mensaje", "format": "message"},
        "exit_criteria": ["Usar artículos"],
    }
}


def _ctx(completion: str) -> CheckContext:
    return CheckContext(
        raw_completion=completion,
        locale_native="en",
        locale_target="es",
        fixture=_FIXTURE,
        mode="lesson",
        case={},
    )


def test_catalog_url_used_pass() -> None:
    result = check_catalog_url_used(
        _ctx(f"Abre [este audio]({_URL}) y escúchalo una vez.")
    )
    assert result.passed


def test_catalog_url_used_rejects_other_youtube() -> None:
    result = check_catalog_url_used(
        _ctx(f"Mira {_URL} y también https://www.youtube.com/watch?v=dQw4w9wgGcQ")
    )
    assert not result.passed
    assert "invented youtube" in result.detail
