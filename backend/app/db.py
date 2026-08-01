from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401 — регистрация моделей

    async with get_engine().begin() as conn:
        await conn.run_sync(_run_migrations)


def _run_migrations(sync_conn) -> None:
    """Alembic-миграции до head. Установки, созданные до перехода на alembic
    (create_all без alembic_version), помечаются базовой ревизией."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.attributes["connection"] = sync_conn

    insp = inspect(sync_conn)
    if insp.has_table("projects") and not insp.has_table("alembic_version"):
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
