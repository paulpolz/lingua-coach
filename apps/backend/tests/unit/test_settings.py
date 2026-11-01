"""Startup guards in Settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

ISSUER = "https://clerk.lingua.example"


def test_production_refuses_to_start_with_langsmith_tracing() -> None:
    with pytest.raises(ValidationError, match="LANGSMITH_TRACING"):
        Settings(_env_file=None, app_env="production", clerk_jwt_issuer=ISSUER, langsmith_tracing=True)


@pytest.mark.parametrize("env", ["local", "staging"])
def test_tracing_is_allowed_outside_production(env: str) -> None:
    assert Settings(_env_file=None, app_env=env, clerk_jwt_issuer=ISSUER, langsmith_tracing=True).langsmith_tracing


def test_tracing_reads_the_langsmith_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CLERK_JWT_ISSUER", ISSUER)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_legacy_langchain_tracing_var_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    with pytest.raises(ValidationError, match="TRACING"):
        Settings(_env_file=None, app_env="production", clerk_jwt_issuer=ISSUER)


def test_unknown_app_env_fails_at_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", clerk_jwt_issuer=ISSUER)  # type: ignore[arg-type]
