"""Shared pytest fixtures for Phase 2 backend tests.

DB-backed tests run against a real, disposable Postgres database
(`lingua_coach_test`) on the same local Postgres instance used for dev
(`docker compose up -d` from the repo root) — SQLite is not viable here since
the ORM models use Postgres-only `JSONB` / `UUID` column types. Tests that
need Postgres depend on the `client` or `db_session` fixtures, which skip
gracefully (rather than failing) if Postgres is unreachable.

Gemini is never called for real in tests — `app.api.v1.chat.stream_chat` is
monkeypatched per-test via the `mock_gemini` fixture.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - populates Base.metadata with every ORM model
from app.api.deps import ClerkPrincipal, get_current_principal
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app

_PG_HOST = "localhost"
_PG_PORT = 5432
_PG_USER = "lingua"
_PG_PASSWORD = "lingua"
_TEST_DB_NAME = "lingua_coach_test"
TEST_DATABASE_URL = (
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{_TEST_DB_NAME}"
)


def _postgres_reachable() -> bool:
    async def _try_connect() -> bool:
        try:
            conn = await asyncpg.connect(
                user=_PG_USER,
                password=_PG_PASSWORD,
                host=_PG_HOST,
                port=_PG_PORT,
                database="postgres",
                timeout=3,
            )
        except Exception:
            return False
        await conn.close()
        return True

    return asyncio.run(_try_connect())


@pytest.fixture(scope="session")
def require_postgres() -> None:
    if not _postgres_reachable():
        pytest.skip(
            "Postgres is not reachable at localhost:5432 — run `docker compose up -d` "
            "from the repo root, then `alembic upgrade head`, before running DB-backed tests."
        )


async def _ensure_test_database_exists() -> None:
    conn = await asyncpg.connect(
        user=_PG_USER, password=_PG_PASSWORD, host=_PG_HOST, port=_PG_PORT, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture()
async def test_engine(require_postgres):
    await _ensure_test_database_exists()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    session_maker = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture()
async def client(test_engine, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """An `httpx.AsyncClient` wired to the FastAPI app with the DB dependency
    pointed at the disposable test database. Auth defaults to no principal set
    (401) — use `as_user()` (returned alongside, see `authed_client`) or set
    `app.dependency_overrides[get_current_principal]` directly per test.

    Also points `app.services.lesson_generation.AsyncSessionLocal` at the
    same test-bound sessionmaker: the lesson-generation `BackgroundTasks`
    callback (Phase 3) runs *after* the request/response cycle, so it can't
    use the `get_db` dependency override above — it opens its own session via
    that module attribute instead, which must resolve to the test DB here.
    """
    session_maker = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.services.lesson_generation.AsyncSessionLocal", session_maker)

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def as_principal(client: AsyncClient) -> Callable[[str, str | None], None]:
    """Override Clerk auth for the current test: `as_principal("clerk_123")`."""

    def _set(clerk_user_id: str, email: str | None = "learner@example.com") -> None:
        async def _override() -> ClerkPrincipal:
            return ClerkPrincipal(clerk_user_id=clerk_user_id, email=email)

        fastapi_app.dependency_overrides[get_current_principal] = _override

    return _set


@pytest.fixture()
def mock_gemini(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], None]:
    """Replace `app.api.v1.chat.stream_chat` with a fake that yields the given
    text chunks, so tests never hit the real Gemini API."""

    def _set(chunks: list[str]) -> None:
        async def _fake_stream_chat(*, system_instruction: str, history: list, **_kw):
            for chunk in chunks:
                yield chunk

        monkeypatch.setattr("app.api.v1.chat.stream_chat", _fake_stream_chat)

    return _set


@pytest.fixture()
def mock_gemini_error(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Replace `app.api.v1.chat.stream_chat` with a fake that raises
    `GeminiError` immediately, simulating an upstream timeout/failure."""

    def _set(message: str = "Gemini request timed out") -> None:
        from app.services.gemini import GeminiError

        async def _fake_stream_chat(*, system_instruction: str, history: list, **_kw):
            raise GeminiError(message, code="LLM_TIMEOUT", error_type="timeout")
            yield  # pragma: no cover - makes this an async generator

        monkeypatch.setattr("app.api.v1.chat.stream_chat", _fake_stream_chat)

    return _set


@pytest.fixture()
def mock_generate_json(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], None]:
    """Replace `app.services.gemini.generate_json` (used by
    app/services/lesson_generation.py) with a fake returning each of `texts`
    in order on successive calls — the first call is the initial generation
    attempt, the second (if any) is the one allowed repair retry — so tests
    never hit the real Gemini API for lesson generation."""

    def _set(texts: list[str]) -> None:
        remaining = list(texts)

        async def _fake_generate_json(*, system_instruction: str, history: list, **_kw) -> str:
            if not remaining:
                raise AssertionError("mock_generate_json called more times than texts provided")
            return remaining.pop(0)

        monkeypatch.setattr("app.services.gemini.generate_json", _fake_generate_json)

    return _set


@pytest.fixture()
def mock_generate_json_error(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Replace `app.services.gemini.generate_json` with a fake that raises
    `GeminiError` immediately, simulating an upstream timeout/failure during
    lesson generation (no repair retry is attempted for this case)."""

    def _set(message: str = "Gemini request timed out") -> None:
        from app.services.gemini import GeminiError

        async def _fake_generate_json(*, system_instruction: str, history: list, **_kw) -> str:
            raise GeminiError(message, code="LLM_TIMEOUT", error_type="timeout")

        monkeypatch.setattr("app.services.gemini.generate_json", _fake_generate_json)

    return _set
