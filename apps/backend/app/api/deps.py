from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clerk_auth import verify_clerk_jwt
from app.core.errors import APIError
from app.db.session import get_db
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


class ClerkPrincipal(BaseModel):
    """Authenticated caller extracted from a verified Clerk JWT."""

    clerk_user_id: str
    email: str | None = None


async def get_clerk_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise APIError(401, "Missing bearer token", "UNAUTHORIZED")
    return await verify_clerk_jwt(credentials.credentials)


async def get_current_principal(claims: dict = Depends(get_clerk_claims)) -> ClerkPrincipal:
    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        raise APIError(401, "Token missing subject claim", "INVALID_TOKEN")
    # Clerk's default session-token template does not include `email`; it is
    # only present if the Clerk instance's session token has been customized
    # with a custom claim (e.g. `{{user.primary_email_address}}`).
    email = claims.get("email")
    return ClerkPrincipal(clerk_user_id=clerk_user_id, email=email)


async def get_current_user(
    principal: ClerkPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the verified Clerk principal to its Postgres `users` row.

    Every authenticated route beyond `/auth/sync` depends on this rather than
    re-querying by `clerk_user_id` itself.
    """
    result = await db.execute(select(User).where(User.clerk_user_id == principal.clerk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise APIError(401, "User not found — call POST /auth/sync first", "USER_NOT_SYNCED")
    return user


async def require_onboarding_complete(user: User = Depends(get_current_user)) -> User:
    """Onboarding gate for lesson routes (readiness §6: `403` when incomplete).

    No lesson routes exist yet (Phase 3+) — this is built now per the plan so
    those routes can depend on it directly, e.g.:
    `user: User = Depends(require_onboarding_complete)` in place of
    `Depends(get_current_user)`.
    """
    if not user.onboarding_complete:
        raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
    return user
