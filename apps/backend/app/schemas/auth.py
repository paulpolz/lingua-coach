from pydantic import BaseModel


class AuthSyncResponse(BaseModel):
    user_id: str
    onboarding_complete: bool
    email: str | None = None
