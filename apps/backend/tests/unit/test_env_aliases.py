"""D13: renamed env vars keep working for one release, with a startup warning."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings, deprecated_env_names

BACKEND_ROOT = Path(__file__).resolve().parents[2]
OLD = {"GEMINI_API_KEY": "old-key", "GEMINI_MODEL_CHAT": "old-chat", "GEMINI_TIMEOUT_SECONDS": "30"}
NEW = {"LLM_API_KEY": "new-key", "LLM_MODEL_CHAT": "new-chat", "LLM_TIMEOUT_SECONDS": "45"}


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*OLD, *NEW, "GEMINI_MODEL_LESSON", "LLM_MODEL_LESSON"]:
        monkeypatch.delenv(name, raising=False)


def test_old_names_still_configure_the_new_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    for name, value in OLD.items():
        monkeypatch.setenv(name, value)
    s = Settings(_env_file=None)
    assert (s.llm_api_key, s.llm_model_chat, s.llm_timeout_seconds) == ("old-key", "old-chat", 30)
    assert deprecated_env_names(None) == sorted(OLD)


def test_new_names_win_and_raise_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    for name, value in NEW.items():
        monkeypatch.setenv(name, value)
    s = Settings(_env_file=None)
    assert (s.llm_api_key, s.llm_model_chat, s.llm_timeout_seconds) == ("new-key", "new-chat", 45)
    assert deprecated_env_names(None) == []


def test_deprecated_names_are_found_in_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_MODEL_LESSON=old-lesson\n")
    assert Settings(_env_file=str(env_file)).llm_model_lesson == "old-lesson"
    assert deprecated_env_names(str(env_file)) == ["GEMINI_MODEL_LESSON"]


def test_only_google_is_a_valid_provider() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_provider="openai")  # type: ignore[arg-type]


@pytest.mark.parametrize(("env", "warned"), [(OLD, True), (NEW, False)])
def test_app_boots_with_either_name_set(tmp_path: Path, env: dict[str, str], warned: bool) -> None:
    """Import the app in a clean process (no .env) with only one naming scheme set."""
    base = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_", "LLM_"))}
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env={**base, **env, "PYTHONPATH": str(BACKEND_ROOT), "APP_ENV": "local", "LANGSMITH_TRACING": "false"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    warnings = [json.loads(line) for line in result.stdout.splitlines() if "deprecated_env_var" in line]
    assert bool(warnings) is warned
    if warned:
        assert {w["old"] for w in warnings} == set(OLD)
