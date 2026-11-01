"""Startup guards in Settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

ISSUER = "https://clerk.lingua.example"


def test_unknown_app_env_fails_at_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", clerk_jwt_issuer=ISSUER)  # type: ignore[arg-type]
