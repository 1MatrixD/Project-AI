"""Курьерское приложение: смены, свои заказы, координаты, чекпойнты."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentCourier, SessionDep
from app.models import Order, Shift, Zone
from app.schemas import CourierOrder, PositionIn, ShiftRead, ShiftStart
from app.services.statuses import ACTIVE_FOR_COURIER, InvalidTransition, OrderStatus, set_status
from app.utils.timeutil import local_day, now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/couriers", tags=["couriers"])


def _open_shift(session: SessionDep, courier_id: int) -> Shift | None:
    """Текущая незакрытая смена курьера."""
    return session.scalar(
        select(Shift).where(Shift.courier_id == courier_id, Shift.ended_at.is_(None))
    )


@router.post("/{courier_id}/shift/start", response_model=ShiftRead, status_code=201)
def start_shift(
    courier_id: int, payload: ShiftStart, session: SessionDep, courier: CurrentCourier
) -> Shift:
    """Открыть смену на зоне.

    Смена относится к московскому дню начала: вышедший в 23:40 курьер весь
    свой выход отработает в рамках сегодняшнего дня.
    """
    if courier.id != courier_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "чужая смена")
    if _open_shift(session, courier.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "смена уже открыта")

    zone = session.get(Zone, payload.zone_id)
    if zone is None or not zone.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "зона не найдена")

    started_at = now_utc()
    shift = Shift(
        courier_id=courier.id,
        zone_id=zone.id,
        started_at=started_at,
        local_date=local_day(started_at),
    )
    session.add(shift)
    session.commit()
    logger.info("shift.start", extra={"courier_id": courier.id, "zone_id": zone.id})
    return shift


@router.post("/{courier_id}/shift/end", response_model=ShiftRead)
def end_shift(courier_id: int, session: SessionDep, courier: CurrentCourier) -> Shift:
    """Закрыть смену. С незавершёнными доставками закрыться нельзя."""
    if courier.id != courier_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "чужая смена")

    shift = _open_shift(session, courier.id)
    if shift is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "открытой смены нет")

    active = session.scalar(
        select(Order.id).where(
            Order.courier_id == courier.id, Order.status.in_(ACTIVE_FOR_COURIER)
        )
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"сначала доставьте заказ №{active}")

    shift.ended_at = now_utc()
    session.commit()
    logger.info("shift.end", extra={"courier_id": courier.id, "shift_id": shift.id})
    return shift


@router.get("/me/orders", response_model=list[CourierOrder])
def my_orders(session: SessionDep, courier: CurrentCourier) -> list[Order]:
    """Заказы, которые сейчас на курьере."""
    stmt = (
        select(Order)
        .where(Order.courier_id == courier.id, Order.status.in_(ACTIVE_FOR_COURIER))
        .order_by(Order.created_at)
    )
    return list(session.scalars(stmt).all())


@router.post("/me/position", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def send_position(payload: PositionIn, session: SessionDep, courier: CurrentCourier) -> None:
    """Приём координат от приложения курьера (раз в 10 секунд на ходу)."""
    courier.lat = payload.lat
    courier.lon = payload.lon
    courier.position_updated_at = now_utc()
    session.commit()


def _courier_order(session: SessionDep, order_id: int, courier_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None or order.courier_id != courier_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")
    return order


@router.post("/me/orders/{order_id}/arrived", response_model=CourierOrder)
def arrived_at_restaurant(order_id: int, session: SessionDep, courier: CurrentCourier) -> Order:
    """Курьер приехал в ресторан."""
    order = _courier_order(session, order_id, courier.id)
    try:
        set_status(session, order, OrderStatus.at_restaurant, actor=f"courier:{courier.id}")
    except InvalidTransition as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    session.commit()
    return order


@router.post("/me/orders/{order_id}/picked-up", response_model=CourierOrder)
def picked_up(order_id: int, session: SessionDep, courier: CurrentCourier) -> Order:
    """Курьер забрал заказ и поехал к клиенту."""
    order = _courier_order(session, order_id, courier.id)
    try:
        set_status(session, order, OrderStatus.picked_up, actor=f"courier:{courier.id}")
        set_status(session, order, OrderStatus.delivering, actor=f"courier:{courier.id}")
    except InvalidTransition as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    session.commit()
    return order


@router.post("/me/orders/{order_id}/delivered", response_model=CourierOrder)
def delivered(order_id: int, session: SessionDep, courier: CurrentCourier) -> Order:
    """Заказ вручён клиенту."""
    order = _courier_order(session, order_id, courier.id)
    try:
        set_status(session, order, OrderStatus.delivered, actor=f"courier:{courier.id}")
    except InvalidTransition as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    session.commit()
    return order
