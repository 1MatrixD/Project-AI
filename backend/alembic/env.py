from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# backend/ на sys.path, чтобы работал `alembic` из любого каталога
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models  # noqa: F401 — регистрация моделей в metadata
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name is not None:
    # не отключаем логгеры приложения — миграции гоняются и на старте API
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к базе (alembic upgrade --sql)."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    # запуск из приложения (init_db): синхронное соединение уже открыто
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:  # запуск из CLI: своя async-сессия
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
