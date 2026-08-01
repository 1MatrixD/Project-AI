"""Подключение к базе и фабрика сессий.

Синхронный SQLAlchemy — сознательное решение: обработчики короткие, а psycopg3
в пуле держит нагрузку. Асинхронный движок трогаем только в SSE-стриме, где
сессия открывается на каждую итерацию отдельно.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=5,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Общий базовый класс для всех моделей."""

    def __repr__(self) -> str:  # pragma: no cover - отладочное
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос.

    Коммитим сами в обработчиках — здесь только гарантированный откат
    незакрытой транзакции и закрытие соединения.
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def session_scope() -> Session:
    """Сессия для фоновых воркеров, где нет DI FastAPI.

    Вызывающий обязан закрыть её сам (`with closing(session_scope()) as s`).
    """
    return SessionLocal()
