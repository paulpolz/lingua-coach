from pydantic import BaseModel


class AuthSyncResponse(BaseModel):
    """Response for `POST /api/v1/auth/sync` — see readiness §6."""

    user_id: str
    onboarding_complete: bool
    email: str | None = None
