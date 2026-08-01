"""Диспетчер: раздаёт оплаченные заказы курьерам.

Крутится внутри процесса приложения. Один инстанс на под — при нескольких
подах гонку снимает `SELECT ... FOR UPDATE SKIP LOCKED`.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.models import Order
from app.services import dispatch
from app.services.statuses import InvalidTransition, OrderStatus, set_status

logger = logging.getLogger(__name__)

#: сколько заказов разбираем за один проход
BATCH_SIZE = 25


def pending_orders(session: Session) -> list[Order]:
    """Оплаченные и готовящиеся заказы без курьера, самые старые первыми."""
    stmt = (
        select(Order)
        .where(
            Order.courier_id.is_(None),
            Order.status.in_((OrderStatus.paid, OrderStatus.cooking)),
        )
        .order_by(Order.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(stmt).all())


def assign_batch() -> int:
    """Один проход диспетчера. Возвращает число назначенных заказов."""
    session = session_scope()
    assigned = 0
    try:
        for order in pending_orders(session):
            courier = dispatch.assign(session, order)
            if courier is None:
                continue
            try:
                if OrderStatus(order.status) == OrderStatus.paid:
                    set_status(session, order, OrderStatus.cooking, actor="worker:assign")
                set_status(session, order, OrderStatus.courier_assigned, actor="worker:assign")
            except InvalidTransition as error:
                logger.warning(
                    "assign.bad_transition",
                    extra={"order_id": order.id, "error": str(error)},
                )
                dispatch.unassign(session, order, "bad_transition")
                continue
            assigned += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return assigned


async def run_forever(stop: asyncio.Event) -> None:
    """Основной цикл. Останавливается по событию из lifespan."""
    logger.info("assign_loop.start", extra={"interval_s": settings.assign_loop_interval_s})
    while not stop.is_set():
        try:
            assigned = await asyncio.to_thread(assign_batch)
            if assigned:
                logger.info("assign_loop.tick", extra={"assigned": assigned})
        except Exception as error:  # noqa: BLE001 - цикл не должен умирать
            logger.exception("assign_loop.failed", extra={"error": str(error)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.assign_loop_interval_s)
        except asyncio.TimeoutError:
            continue
    logger.info("assign_loop.stop")
