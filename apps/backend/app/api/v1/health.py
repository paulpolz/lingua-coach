from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Liveness + lightweight DB readiness check for local Grafana / ops smoke tests."""
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
