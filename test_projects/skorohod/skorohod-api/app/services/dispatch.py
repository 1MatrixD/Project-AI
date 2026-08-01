"""Диспетчеризация: кому отдать заказ.

Основной потребитель — фоновый цикл `workers/assign_loop.py`, который раз в
несколько секунд разгребает оплаченные заказы без курьера.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Courier, Order, Shift, Zone
from app.services import zones as zones_service
from app.services.statuses import ACTIVE_FOR_COURIER

logger = logging.getLogger(__name__)


def open_shifts(session: Session) -> dict[int, Shift]:
    """Открытые смены (без `ended_at`) словарём `courier_id -> смена`."""
    shifts = session.scalars(select(Shift).where(Shift.ended_at.is_(None))).all()
    return {shift.courier_id: shift for shift in shifts}


def busy_courier_ids(session: Session) -> set[int]:
    """Курьеры, у которых уже есть заказ в работе."""
    stmt = select(Order.courier_id).where(
        Order.courier_id.is_not(None),
        Order.status.in_(ACTIVE_FOR_COURIER),
    )
    return {courier_id for courier_id in session.scalars(stmt).all() if courier_id}


def free_couriers(session: Session) -> list[Courier]:
    """Активные курьеры без текущей доставки."""
    busy = busy_courier_ids(session)
    stmt = select(Courier).where(Courier.is_active.is_(True))
    return [courier for courier in session.scalars(stmt).all() if courier.id not in busy]


def pick_courier(session: Session, order: Order, couriers: list[Courier]) -> Courier | None:
    """Выбрать курьера для заказа.

    Берём ближайшего свободного курьера, чья зона (полигон) покрывает адрес
    доставки. Курьеры без открытой смены и курьеры из чужих зон отсеиваются,
    среди оставшихся побеждает тот, кому ехать меньше всего.

    Возвращает `None`, если подходящих курьеров нет — заказ останется в
    очереди до следующей итерации диспетчера.
    """
    if not couriers:
        return None

    point = (order.lat, order.lon)
    shifts = open_shifts(session)
    zone_by_id: dict[int, Zone] = zones_service.zones_bulk(session)

    candidates: list[Courier] = []
    for courier in couriers:
        shift = shifts.get(courier.id)
        if shift is None:
            continue
        zone = zone_by_id.get(shift.zone_id)
        if zone is None:
            continue
        if not zones_service.bbox_contains(zone.bbox, point):
            continue
        candidates.append(courier)

    if not candidates:
        logger.info("dispatch.no_candidates", extra={"order_id": order.id})
        return None

    candidates = sorted(candidates, key=lambda courier: courier.id)
    chosen = candidates[0]
    logger.info(
        "dispatch.picked",
        extra={"order_id": order.id, "courier_id": chosen.id, "candidates": len(candidates)},
    )
    return chosen


def assign(session: Session, order: Order) -> Courier | None:
    """Назначить курьера на заказ.

    Записывает `order.courier_id`, но статус не трогает — это делает
    вызывающий через `statuses.set_status`, чтобы уведомление ушло один раз.
    """
    if order.courier_id is not None:
        return session.get(Courier, order.courier_id)

    courier = pick_courier(session, order, free_couriers(session))
    if courier is None:
        return None

    order.courier_id = courier.id
    session.flush()
    return courier


def unassign(session: Session, order: Order, reason: str) -> None:
    """Снять курьера с заказа (отказ, отмена, конец смены)."""
    if order.courier_id is None:
        return
    logger.info(
        "dispatch.unassign",
        extra={"order_id": order.id, "courier_id": order.courier_id, "reason": reason},
    )
    order.courier_id = None
    session.flush()
