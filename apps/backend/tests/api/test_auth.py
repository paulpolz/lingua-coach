"""Clerk JWT verification end to end (real verifier, JWKS fetch stubbed)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk
from jose import jwt as jose_jwt
from pydantic import ValidationError

from app.config import Settings, settings
from app.core import clerk_auth
from app.main import app
from tests.conftest import Auth

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
_PUBLIC_PEM = (
    _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
)
_JWKS = {"keys": [{**jwk.construct(_PUBLIC_PEM, "RS256").to_dict(), "kid": "k1", "alg": "RS256"}]}

PROD_ISSUER = "https://clerk.lingua.example"
FOREIGN_DEV_ISSUER = "https://attacker-app.clerk.accounts.dev"


def _token(iss: str, **claims: Any) -> str:
    now = int(time.time())
    body = {"iss": iss, "sub": "user_jwt", "iat": now, "nbf": now - 5, "exp": now + 300, **claims}
    return jose_jwt.encode(body, _PRIVATE_PEM, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
async def real_auth_client(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The shared client, but with the real Clerk dependency instead of the override."""
    from app.api.deps import get_current_principal

    app.dependency_overrides.pop(get_current_principal, None)

    async def fetch(issuer: str) -> dict[str, Any]:
        return _JWKS

    monkeypatch.setattr(clerk_auth, "_fetch_jwks", fetch)
    clerk_auth._jwks_cache.clear()
    yield client


async def _sync(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/sync", headers={"Authorization": f"Bearer {token}"})


async def test_foreign_dev_issuer_rejected_in_production(
    real_auth_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "")

    response = await _sync(real_auth_client, _token(FOREIGN_DEV_ISSUER))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


async def test_configured_issuer_accepted_in_production(
    real_auth_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", PROD_ISSUER)

    assert (await _sync(real_auth_client, _token(PROD_ISSUER))).status_code == 200
    assert (await _sync(real_auth_client, _token(FOREIGN_DEV_ISSUER))).status_code == 401


async def test_dev_issuer_pattern_still_accepted_locally(real_auth_client: httpx.AsyncClient) -> None:
    assert settings.app_env == "local"
    assert (await _sync(real_auth_client, _token(FOREIGN_DEV_ISSUER))).status_code == 200


@pytest.mark.parametrize(
    ("azp", "status"),
    [("http://localhost:3000", 200), ("https://evil.example", 401), (None, 200)],
)
async def test_azp_must_be_an_allowed_origin(real_auth_client: httpx.AsyncClient, azp: str | None, status: int) -> None:
    claims = {"azp": azp} if azp else {}
    assert (await _sync(real_auth_client, _token(FOREIGN_DEV_ISSUER, **claims))).status_code == status


async def test_missing_bearer_token_is_401(real_auth_client: httpx.AsyncClient) -> None:
    response = await real_auth_client.post("/api/v1/auth/sync")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_sync_is_idempotent(client: httpx.AsyncClient, auth: Auth) -> None:
    first = await client.post("/api/v1/auth/sync")
    second = await client.post("/api/v1/auth/sync")
    assert first.status_code == second.status_code == 200
    assert first.json()["user_id"] == second.json()["user_id"]


@pytest.mark.parametrize("env", ["staging", "production"])
def test_settings_require_issuer_outside_local(env: str) -> None:
    with pytest.raises(ValidationError, match="CLERK_JWT_ISSUER"):
        Settings(_env_file=None, app_env=env, clerk_jwt_issuer="")
    assert Settings(_env_file=None, app_env=env, clerk_jwt_issuer=PROD_ISSUER).clerk_jwt_issuer == PROD_ISSUER
