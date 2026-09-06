"""Alembic environment for accounts_db. Reads the DB URL from
core_config.Config.SUPABASE_DB_URL (same settings system as the rest of the
main backend) rather than a separate alembic.ini-hardcoded URL -- so this
migration runner always targets whatever the running deployment is
actually configured for. Alembic's migration runner is sync, so an
asyncpg-style URL is downgraded to psycopg2 here specifically for this
process; app_api's own runtime engine (accounts_db/database.py) still uses
asyncpg."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from accounts_db.models import Base  # noqa: E402
from core_config import Config  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_db_url() -> str:
    if not Config.SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL is not set -- required to run migrations.")
    return Config.SUPABASE_DB_URL.replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_db_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
