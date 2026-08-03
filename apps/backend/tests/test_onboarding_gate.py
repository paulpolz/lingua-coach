"""`require_onboarding_complete` dependency — 403 gate for future lesson routes."""

from __future__ import annotations

import pytest

from app.api.deps import require_onboarding_complete
from app.core.errors import APIError
from app.models.user import User


async def test_gate_raises_403_when_onboarding_incomplete() -> None:
    user = User(clerk_user_id="clerk_gate_incomplete", onboarding_complete=False)
    with pytest.raises(APIError) as exc_info:
        await require_onboarding_complete(user=user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "ONBOARDING_INCOMPLETE"


async def test_gate_passes_through_when_onboarding_complete() -> None:
    user = User(clerk_user_id="clerk_gate_complete", onboarding_complete=True)
    result = await require_onboarding_complete(user=user)
    assert result is user
