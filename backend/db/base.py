"""Async SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_engine_url: str | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Create the global engine + session factory.

    Rebuilds if the URL changes (e.g. across tests pointing at fresh SQLite
    files); otherwise returns the existing engine.
    """
    global _engine, _engine_url, _sessionmaker
    if _engine is None or _engine_url != database_url:
        _engine = create_async_engine(database_url, pool_pre_ping=True, future=True)
        _engine_url = database_url
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Engine not initialized; call init_engine() first.")
    return _sessionmaker


async def create_all() -> None:
    """Create tables from the models (dev convenience; use Alembic in prod)."""
    # Import models so they register on Base.metadata before create_all.
    from db import models  # noqa: F401

    engine = _engine
    if engine is None:
        raise RuntimeError("Engine not initialized; call init_engine() first.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, committing on success."""
    async with get_sessionmaker()() as session:
        yield session
