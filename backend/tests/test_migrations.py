"""Alembic: свежая БД мигрируется на старте, старые установки стампятся базой."""
from __future__ import annotations

import asyncpg
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .conftest import TEST_DB_URL, _pg_password


async def test_fresh_db_is_migrated(client: httpx.AsyncClient) -> None:
    """conftest вызывает init_db() на пустой БД → alembic доводит её до head."""
    from app.db import get_engine

    async with get_engine().connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        tables = (
            await conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            )
        ).scalar()
    assert version == "0001"
    assert tables >= 12  # 11 таблиц моделей + alembic_version


async def test_legacy_install_gets_stamped(client: httpx.AsyncClient) -> None:
    """БД, созданная старым create_all (до alembic), при init помечается ревизией 0001."""
    from app.db import Base, _run_migrations

    admin = await asyncpg.connect(
        user="projectai", password=_pg_password, database="projectai", host="localhost", port=5432
    )
    try:
        await admin.execute("DROP DATABASE IF EXISTS projectai_legacy_test WITH (FORCE)")
        await admin.execute("CREATE DATABASE projectai_legacy_test")
    finally:
        await admin.close()

    url = TEST_DB_URL.rsplit("/", 1)[0] + "/projectai_legacy_test"
    engine = create_async_engine(url)
    try:
        # «старая установка»: схема есть, alembic_version нет
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.begin() as conn:
            await conn.run_sync(_run_migrations)
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
        assert version == "0001"
    finally:
        await engine.dispose()
