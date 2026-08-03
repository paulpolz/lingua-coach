"""Stateless Clerk session-JWT verification via JWKS.

Verifies the `Authorization: Bearer <clerk_jwt>` header without storing
sessions in Postgres (Clerk owns sessions; see docs/tech_requirements/database.md).

Flow:
1. Read the `iss` claim from the *unverified* token.
2. Confirm `iss` against an allow-list/pattern (either an exact
   `CLERK_JWT_ISSUER` override, or the default Clerk Development pattern
   `https://*.clerk.accounts.dev`) — never fetch JWKS from an arbitrary host.
3. Fetch (and cache) `{iss}/.well-known/jwks.json`.
4. Verify the token signature + standard claims against the matching JWK.
"""

import re
import time

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

from app.config import settings
from app.core.errors import APIError

_DEV_ISSUER_PATTERN = re.compile(r"^https://[a-zA-Z0-9-]+\.clerk\.accounts\.dev$")

_JWKS_CACHE_TTL_SECONDS = 3600
_jwks_cache: dict[str, tuple[float, dict]] = {}


def _is_allowed_issuer(issuer: str) -> bool:
    if settings.clerk_jwt_issuer:
        return issuer == settings.clerk_jwt_issuer
    return bool(_DEV_ISSUER_PATTERN.match(issuer))


async def _fetch_jwks(issuer: str) -> dict:
    url = f"{issuer}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _get_jwks(issuer: str, *, force_refresh: bool = False) -> dict:
    now = time.monotonic()
    cached = _jwks_cache.get(issuer)
    if not force_refresh and cached is not None and now - cached[0] < _JWKS_CACHE_TTL_SECONDS:
        return cached[1]
    jwks = await _fetch_jwks(issuer)
    _jwks_cache[issuer] = (now, jwks)
    return jwks


async def verify_clerk_jwt(token: str) -> dict:
    """Verify a Clerk session token and return its decoded claims.

    Raises `APIError(401, ...)` for any missing/invalid/expired token.
    """
    try:
        unverified_claims = jose_jwt.get_unverified_claims(token)
        unverified_header = jose_jwt.get_unverified_header(token)
    except JWTError as exc:
        raise APIError(401, f"Malformed token: {exc}", "INVALID_TOKEN") from exc

    issuer = unverified_claims.get("iss")
    if not issuer or not isinstance(issuer, str) or not _is_allowed_issuer(issuer):
        raise APIError(401, "Untrusted or missing token issuer", "INVALID_TOKEN")

    kid = unverified_header.get("kid")
    if not kid:
        raise APIError(401, "Token missing key id", "INVALID_TOKEN")

    try:
        jwks = await _get_jwks(issuer)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            # Key rotation: refresh once before giving up.
            jwks = await _get_jwks(issuer, force_refresh=True)
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise APIError(401, "Unknown signing key", "INVALID_TOKEN")

        claims = jose_jwt.decode(
            token,
            key,
            algorithms=[key.get("alg", "RS256")],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except APIError:
        raise
    except JWTError as exc:
        raise APIError(401, f"Invalid token: {exc}", "INVALID_TOKEN") from exc
    except httpx.HTTPError as exc:
        raise APIError(401, f"Unable to verify token: {exc}", "INVALID_TOKEN") from exc

    return claims
