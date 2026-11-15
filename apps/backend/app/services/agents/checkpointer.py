"""LangGraph checkpoint connection. Separate from the SQLAlchemy asyncpg pool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import settings


def checkpoint_postgres_url(database_url: str) -> str:
    """psycopg URL. Same swap Alembic makes, without the `+psycopg` driver name."""
    if "+asyncpg" in database_url:
        return database_url.replace("+asyncpg", "", 1)
    prefix = "postgresql+psycopg://"
    if database_url.startswith(prefix):
        return "postgresql://" + database_url.removeprefix(prefix)
    return database_url


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Hold one saver for the process. `setup()` is idempotent (spike, 14 Nov 2026)."""
    async with AsyncPostgresSaver.from_conn_string(checkpoint_postgres_url(settings.database_url)) as saver:
        await saver.setup()
        yield saver
