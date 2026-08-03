from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ClerkPrincipal, get_current_principal
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import AuthSyncResponse

router = APIRouter(prefix="/auth", tags=["auth"])


async def _get_user_by_clerk_id(db: AsyncSession, clerk_user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    return result.scalar_one_or_none()


@router.post("/sync", response_model=AuthSyncResponse)
async def sync_user(
    principal: ClerkPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> AuthSyncResponse:
    """Idempotently upsert a `users` row keyed by `clerk_user_id`.

    Creates the row on first authenticated call; on subsequent calls,
    refreshes the cached email if Clerk supplied one on the token.
    """
    user = await _get_user_by_clerk_id(db, principal.clerk_user_id)

    if user is None:
        user = User(clerk_user_id=principal.clerk_user_id, email=principal.email)
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent first request from the same user raced us — fall
            # back to the row the other request created.
            await db.rollback()
            user = await _get_user_by_clerk_id(db, principal.clerk_user_id)
            if user is None:
                raise
    elif principal.email and user.email != principal.email:
        user.email = principal.email
        await db.commit()

    await db.refresh(user)
    return AuthSyncResponse(
        user_id=str(user.id),
        onboarding_complete=user.onboarding_complete,
        email=user.email,
    )
