"""Уборщик зависших заказов.

Заказ, который повис в `created` дольше `stale_order_minutes`, — это почти
всегда брошенная оплата: пользователь ушёл с формы банка и не вернулся.
Холд по такому заказу отпускаем, сам заказ отменяем, чтобы он не мозолил
глаза в списке и не влиял на surge.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.models import Order, Payment
from app.services import payments as payments_service
from app.services.statuses import InvalidTransition, OrderStatus, set_status
from app.utils.timeutil import now_utc

logger = logging.getLogger(__name__)

#: как часто проверяем
INTERVAL_S = 60.0


def stale_orders(session: Session) -> list[Order]:
    """Заказы в `created`, созданные слишком давно."""
    deadline = now_utc() - timedelta(minutes=settings.stale_order_minutes)
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.created, Order.created_at < deadline)
        .order_by(Order.created_at)
        .limit(50)
    )
    return list(session.scalars(stmt).all())


def release_hold(session: Session, order: Order) -> None:
    """Вернуть незавершённый холд провайдеру."""
    payment = session.scalar(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc())
    )
    if payment is None or payment.status != "hold":
        return
    try:
        payments_service.refund(payment.provider_id, payment.amount_kop, reason="stale_order")
        payment.status = "refunded"
    except payments_service.ProviderError as error:
        # Не страшно: холд у провайдера протухнет сам через сутки.
        logger.warning(
            "stale.release_failed",
            extra={"order_id": order.id, "error": str(error)},
        )


def cancel_batch() -> int:
    """Один проход уборщика. Возвращает число отменённых заказов."""
    session = session_scope()
    cancelled = 0
    try:
        for order in stale_orders(session):
            release_hold(session, order)
            try:
                set_status(session, order, OrderStatus.cancelled, actor="worker:stale")
            except InvalidTransition as error:
                logger.warning(
                    "stale.bad_transition", extra={"order_id": order.id, "error": str(error)}
                )
                continue
            cancelled += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return cancelled


async def run_forever(stop: asyncio.Event) -> None:
    """Основной цикл уборщика."""
    logger.info("stale_orders.start", extra={"minutes": settings.stale_order_minutes})
    while not stop.is_set():
        try:
            cancelled = await asyncio.to_thread(cancel_batch)
            if cancelled:
                logger.info("stale_orders.tick", extra={"cancelled": cancelled})
        except Exception as error:  # noqa: BLE001 - цикл не должен умирать
            logger.exception("stale_orders.failed", extra={"error": str(error)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_S)
        except asyncio.TimeoutError:
            continue
    logger.info("stale_orders.stop")
