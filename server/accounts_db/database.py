"""Async engine/session factory for accounts_db's Postgres tables. Not
imported by app_api yet -- see accounts_db/README.md. Reuses the main
backend's one settings system (core_config.Config) rather than inventing a
second one the way rules_mcp/discord_client do for their standalone-
deployable-service reasons -- this package is a library for app_api, not
its own service."""

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

from core_config import Config

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        if not Config.SUPABASE_DB_URL:
            raise RuntimeError(
                "SUPABASE_DB_URL is not set -- accounts_db is scaffolding-only "
                "until Phase 1 wires ACCOUNTS_MODE=hosted into app_api."
            )
        _engine = create_async_engine(Config.SUPABASE_DB_URL)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory
