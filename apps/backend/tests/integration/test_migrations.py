"""Alembic migrations on a scratch database: data-merging steps and downgrade round trips.

(`c2d5e8f1a3b7` is deliberately irreversible, so round trips start above it.)
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import settings
from tests.conftest import BACKEND_ROOT, TEST_DATABASE_URL

PRE_INTEGRITY = "c2d5e8f1a3b7"
INTEGRITY = "9a1f3c5e7b2d"


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Config, Engine]]:
    name = f"lingua_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(make_url(TEST_DATABASE_URL).set(drivername="postgresql+psycopg"), poolclass=NullPool)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(TEST_DATABASE_URL).set(database=name)
    monkeypatch.setattr(settings, "database_url", url.render_as_string(hide_password=False))
    config = Config()  # no ini: its fileConfig() would disable the app loggers
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    engine = create_engine(url.set(drivername="postgresql+psycopg"), poolclass=NullPool)
    try:
        yield config, engine
    finally:
        engine.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_integrity_migration_merges_duplicates_and_round_trips(scratch: tuple[Config, Engine]) -> None:
    config, engine = scratch
    command.upgrade(config, PRE_INTEGRITY)
    user = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, clerk_user_id) VALUES (:u, 'mig')"), {"u": user})
        for number, status in [(1, "active"), (2, "generating"), (3, "accomplished")]:
            conn.execute(
                text("INSERT INTO lessons (id, user_id, lesson_number, payload, status) VALUES (:i, :u, :n, '{}', :s)"),
                {"i": uuid.uuid4(), "u": user, "n": number, "s": status},
            )
        for count, seen in [(2, "2026-10-01"), (3, "2026-10-05")]:
            conn.execute(
                text(
                    "INSERT INTO mistakes (id, user_id, pattern_type, example_text, occurrence_count, last_seen_at)"
                    " VALUES (:i, :u, 'articles', :e, :c, :s)"
                ),
                {"i": uuid.uuid4(), "u": user, "e": f"seen {seen}", "c": count, "s": seen},
            )

    command.upgrade(config, INTEGRITY)

    with engine.connect() as conn:
        statuses = dict(conn.execute(text("SELECT lesson_number, status FROM lessons")).all())
        mistakes = conn.execute(text("SELECT example_text, occurrence_count FROM mistakes")).all()
    assert statuses == {1: "failed", 2: "generating", 3: "accomplished"}
    assert [tuple(m) for m in mistakes] == [("seen 2026-10-05", 5)]

    command.upgrade(config, "head")
    command.downgrade(config, PRE_INTEGRITY)
    command.upgrade(config, "head")
