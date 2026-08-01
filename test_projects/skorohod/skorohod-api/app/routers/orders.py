"""Заказы, версия 2. Основной чекаут для сайта и мобилки >= 3.0."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.models import Address, MenuItem, Order, OrderItem, Payment, Restaurant
from app.schemas import CancelRequest, OrderCreate, OrderListItem, OrderRead
from app.services import dispatch, payments as payments_service, pricing
from app.services import promo as promo_service
from app.services.statuses import OrderStatus, set_status
from app.utils.money import clamp_non_negative
from app.utils.timeutil import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/orders", tags=["orders"])

#: статусы, из которых пользователь ещё может отменить заказ сам
CANCELLABLE = (OrderStatus.created, OrderStatus.paid, OrderStatus.cooking)


def _collect_items(session: SessionDep, restaurant_id: int, requested) -> list[tuple[MenuItem, int]]:
    """Достать позиции меню и проверить, что они из нужного ресторана."""
    ids = [item.menu_item_id for item in requested]
    rows = session.scalars(select(MenuItem).where(MenuItem.id.in_(ids))).all()
    menu = {row.id: row for row in rows}
    result: list[tuple[MenuItem, int]] = []
    for item in requested:
        menu_item = menu.get(item.menu_item_id)
        if menu_item is None or menu_item.restaurant_id != restaurant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"позиция {item.menu_item_id} не найдена")
        if not menu_item.is_available:
            raise HTTPException(status.HTTP_409_CONFLICT, f"«{menu_item.name}» закончилась")
        result.append((menu_item, item.qty))
    return result


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, session: SessionDep, user: CurrentUser) -> Order:
    """Оформить заказ: посчитать чек, применить промокод, поставить холд."""
    restaurant = session.get(Restaurant, payload.restaurant_id)
    if restaurant is None or not restaurant.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ресторан недоступен")

    address = session.get(Address, payload.address_id)
    if address is None or address.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "адрес не найден")

    positions = _collect_items(session, restaurant.id, payload.items)
    subtotal_kop = sum(menu_item.price_kop * qty for menu_item, qty in positions)

    point = (address.lat, address.lon)
    now = now_utc()
    try:
        delivery = pricing.calc_delivery(session, restaurant, point, subtotal_kop, now)
    except pricing.DeliveryUnavailable as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    discount_kop = 0
    promo = promo_service.find_promo(session, payload.promo_code)
    if payload.promo_code:
        check = promo_service.validate_promo(session, promo, user.id, subtotal_kop, now)
        if not check.ok:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"промокод: {check.reason}")
        discount_kop = check.discount_kop

    total_kop = clamp_non_negative(subtotal_kop + delivery.total_kop - discount_kop)

    order = Order(
        user_id=user.id,
        restaurant_id=restaurant.id,
        address_id=address.id,
        status=OrderStatus.created,
        subtotal_kop=subtotal_kop,
        delivery_kop=delivery.total_kop,
        discount_kop=discount_kop,
        total_kop=total_kop,
        promo_code=promo.code if promo is not None else None,
        comment=payload.comment,
        lat=address.lat,
        lon=address.lon,
        created_at=now,
    )
    session.add(order)
    session.flush()

    for menu_item, qty in positions:
        session.add(
            OrderItem(order_id=order.id, menu_item_id=menu_item.id, name=menu_item.name,
                      price_kop=menu_item.price_kop, qty=qty)
        )

    try:
        hold = payments_service.create_hold(order.id, total_kop, user.phone)
    except payments_service.ProviderError as error:
        session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"платёж не прошёл: {error}") from error

    session.add(
        Payment(order_id=order.id, provider_id=str(hold.get("id", "")),
                amount_kop=total_kop, status="hold")
    )
    session.commit()
    logger.info("order.created", extra={"order_id": order.id, "total_kop": total_kop})
    return order


@router.get("", response_model=list[OrderListItem])
def list_orders(
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Order]:
    """Свои заказы, свежие сверху."""
    stmt = (
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt).all())


def _own_order(session: SessionDep, order_id: int, user_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")
    return order


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: int, session: SessionDep, user: CurrentUser) -> Order:
    """Карточка заказа со составом."""
    return _own_order(session, order_id, user.id)


@router.post("/{order_id}/cancel", response_model=OrderRead)
def cancel_order(
    order_id: int, payload: CancelRequest, session: SessionDep, user: CurrentUser
) -> Order:
    """Отменить заказ и вернуть деньги, если холд уже списан."""
    order = _own_order(session, order_id, user.id)
    if OrderStatus(order.status) not in CANCELLABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "заказ уже нельзя отменить")

    payment = session.scalar(select(Payment).where(Payment.order_id == order.id))
    if payment is not None and payment.status == "captured":
        try:
            payments_service.refund(payment.provider_id, payment.amount_kop, payload.reason)
        except payments_service.ProviderError as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
        payment.status = "refunded"

    dispatch.unassign(session, order, payload.reason)
    set_status(session, order, OrderStatus.cancelled, actor=f"user:{user.id}")
    session.commit()
    return order


@router.post("/{order_id}/repeat", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def repeat_order(order_id: int, session: SessionDep, user: CurrentUser) -> Order:
    """Повторить заказ: тот же состав и адрес, цены — по текущему меню."""
    source = _own_order(session, order_id, user.id)
    payload = OrderCreate(
        restaurant_id=source.restaurant_id,
        address_id=source.address_id,
        items=[{"menu_item_id": item.menu_item_id, "qty": item.qty} for item in source.items],
        promo_code=source.promo_code,
        comment=source.comment,
    )
    return create_order(payload, session, user)
