from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensures `app.*` is importable regardless of the CWD Alembic was invoked
# from ("." is on sys.path via alembic.ini's prepend_sys_path, but be explicit
# in case alembic is ever invoked from the repo root).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (imports all models -> populates metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    """Alembic runs synchronously; swap the asyncpg driver for psycopg (sync).

    Runtime app code keeps using `postgresql+asyncpg://` from DATABASE_URL —
    this only affects the URL Alembic uses for migrations.
    """
    url = settings.database_url
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg")
    return url


config.set_main_option("sqlalchemy.url", _sync_database_url())


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
