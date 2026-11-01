"""Shared fixtures: real Postgres, per-test SAVEPOINT rollback, auth override, fake LLM.

Every test runs inside one outer transaction on one connection. App sessions, background
job sessions and the limiter's side session all join that connection with SAVEPOINTs, so
their `commit()` calls never reach the database and the outer rollback discards
everything. Tests that need real concurrency use `committed_client` instead.
"""

from __future__ import annotations

import os

# Settings are read once at import time, so pin them before any `app` import. Explicit
# values also override a developer's apps/backend/.env.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://lingua:lingua@localhost:5432/lingua_test")
# Live evals (`-m eval`) need the real key; everything else runs on a fake one, so an
# accidental unmocked call fails fast instead of spending money.
os.environ["EVAL_GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY") or ""
os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "APP_ENV": "local",
        "CLERK_JWT_ISSUER": "",
        "CORS_ORIGINS": "http://localhost:3000",
        "GEMINI_API_KEY": "test-key",
        "LANGSMITH_TRACING": "false",
        "CHAT_RATE_LIMIT_PER_HOUR": "1000",
        "LESSON_START_RATE_LIMIT_PER_DAY": "1000",
        "LLM_RPM_LIMIT": "1000",
        "LLM_RPD_LIMIT": "100000",
        "LLM_INPUT_TPM_LIMIT": "100000000",
    }
)

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.api.deps import ClerkPrincipal, get_current_principal  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.fake_llm import FakeLLM, install_fake_llm  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Modules that open their own session with `AsyncSessionLocal()` (background jobs).
BACKGROUND_SESSION_TARGETS = (
    "app.services.lesson_generation.AsyncSessionLocal",
    "app.services.report_writer.AsyncSessionLocal",
)


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Fresh schema, then `alembic upgrade head` once per test session."""
    sync_engine = create_engine(_sync_url(TEST_DATABASE_URL), poolclass=NullPool)
    with sync_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    sync_engine.dispose()
    config = Config()  # no ini: its fileConfig() would disable the app loggers
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        yield conn
        await outer.rollback()


def _joined_session(conn: AsyncConnection) -> AsyncSession:
    return AsyncSession(bind=conn, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint")


@pytest.fixture
async def db(db_conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """The test's own session (factories, assertions). Call `db.expire_all()` before re-reading."""
    session = _joined_session(db_conn)
    yield session
    await session.close()


@dataclass
class Auth:
    """The principal every request authenticates as. Switch users with `as_clerk_id`."""

    principal: ClerkPrincipal = field(default_factory=lambda: ClerkPrincipal(clerk_user_id="user_test"))

    def as_clerk_id(self, clerk_user_id: str) -> None:
        self.principal = ClerkPrincipal(clerk_user_id=clerk_user_id)


@pytest.fixture
def auth() -> Auth:
    return Auth()


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    fake = FakeLLM()
    with install_fake_llm(fake, monkeypatch):
        yield fake


@pytest.fixture
def background_sessions(db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Background jobs open their sessions on the test connection too."""
    for target in BACKGROUND_SESSION_TARGETS:
        monkeypatch.setattr(target, lambda: _joined_session(db_conn))


@pytest.fixture
async def client(db_conn: AsyncConnection, auth: Auth, background_sessions: None) -> AsyncIterator[httpx.AsyncClient]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        session = _joined_session(db_conn)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_principal] = lambda: auth.principal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --- Committed mode: real transactions for concurrency tests --------------------


@pytest.fixture
async def committed_sessions(engine: AsyncEngine) -> AsyncIterator[Callable[[], AsyncSession]]:
    """A session factory whose commits are real. Truncates every table afterwards."""

    def factory() -> AsyncSession:
        return AsyncSession(bind=engine, expire_on_commit=False, autoflush=False)

    yield factory
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
            )
        ).scalars()
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


@pytest.fixture
async def committed_client(
    committed_sessions: Callable[[], AsyncSession], auth: Auth, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with committed_sessions() as session:
            yield session

    for target in BACKGROUND_SESSION_TARGETS:
        monkeypatch.setattr(target, committed_sessions)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_principal] = lambda: auth.principal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def error_code(response: httpx.Response) -> Any:
    return response.json().get("code")
