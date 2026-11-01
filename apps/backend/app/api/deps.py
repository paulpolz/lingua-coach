import uuid
from typing import TypeVar

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clerk_auth import verify_clerk_jwt
from app.core.errors import APIError
from app.db.session import get_db
from app.models.chat import ChatSession
from app.models.job import Job
from app.models.lesson import Lesson
from app.models.user import User

Owned = TypeVar("Owned", Lesson, ChatSession, Job)

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
    result = await db.execute(select(User).where(User.clerk_user_id == principal.clerk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise APIError(401, "User not found — call POST /auth/sync first", "USER_NOT_SYNCED")
    return user


async def require_onboarding_complete(user: User = Depends(get_current_user)) -> User:
    if not user.onboarding_complete:
        raise APIError(403, "Onboarding not complete", "ONBOARDING_INCOMPLETE")
    return user


async def get_owned(db: AsyncSession, model: type[Owned], ident: uuid.UUID, user: User, what: str) -> Owned:
    """Load a row the caller owns. Path ids are typed `uuid.UUID`, so a malformed id is already
    a 422; a well-formed id that is missing or someone else's is a 404 (no existence leak)."""
    row = await db.get(model, ident)
    if row is None or row.user_id != user.id:
        raise APIError(404, f"{what} not found", "NOT_FOUND")
    return row
