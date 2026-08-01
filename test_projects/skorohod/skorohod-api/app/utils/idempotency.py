"""Идемпотентность обработки внешних событий.

Платёжный провайдер ретраит вебхуки при любом таймауте или 5xx, поэтому одно
и то же событие может приехать несколько раз. Защита простая: таблица
`webhook_events` с уникальным `event_id`.

Использование:

    if already_processed(session, event_id):
        return {"ok": True}
    ...  # полезная работа
    mark_processed(session, event_id, event_type)
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import WebhookEvent
from app.utils.timeutil import now_utc

logger = logging.getLogger(__name__)


def already_processed(session: Session, event_id: str) -> bool:
    """Видели ли мы уже событие с таким `event_id`."""
    if not event_id:
        # Событие без идентификатора обработать идемпотентно нельзя,
        # считаем его новым и полагаемся на проверки выше по стеку.
        return False
    stmt = select(WebhookEvent.id).where(WebhookEvent.event_id == event_id)
    return session.scalar(stmt) is not None


def mark_processed(session: Session, event_id: str, event_type: str) -> None:
    """Отметить событие обработанным.

    Гонка двух параллельных доставок одного события ловится уникальным
    индексом: второй инстанс получит IntegrityError и просто откатит вставку.
    """
    if not event_id:
        return
    event = WebhookEvent(
        event_id=event_id,
        type=event_type,
        received_at=now_utc(),
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        logger.warning("webhook.duplicate", extra={"event_id": event_id})


def processed_count(session: Session, event_type: str) -> int:
    """Сколько событий такого типа мы уже приняли. Нужно для метрик."""
    stmt = select(WebhookEvent).where(WebhookEvent.type == event_type)
    return len(session.scalars(stmt).all())
