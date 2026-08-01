"""Legacy-чекаут `/api/v1/checkout`.

Сюда ходит мобильное приложение версий ниже 3.0: другое тело запроса
(`restaurant`/`address`/`items[].count`) и другой формат ответа — рубли
строкой и поле `state` вместо `status`.

Сценарий тот же, что в `routers/orders.py`: собрать корзину, посчитать
доставку, применить промокод, поставить холд.

Удалить вместе с релизом 4.2.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep
from app.models import Address, MenuItem, Order, OrderItem, Payment, PromoUsage, Restaurant
from app.schemas import CheckoutRequestV1, CheckoutResponseV1
from app.services import payments as payments_service, pricing
from app.services import promo as promo_service
from app.services.statuses import OrderStatus
from app.utils.money import clamp_non_negative, kop_to_rub
from app.utils.timeutil import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["legacy"])


@router.post("/checkout", response_model=CheckoutResponseV1)
def checkout(payload: CheckoutRequestV1, session: SessionDep, user: CurrentUser) -> CheckoutResponseV1:
    """Оформление заказа из старого приложения."""
    restaurant = session.get(Restaurant, payload.restaurant)
    if restaurant is None or not restaurant.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ресторан недоступен")

    address = session.get(Address, payload.address)
    if address is None or address.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "адрес не найден")

    ids = [item.id for item in payload.items]
    menu = {
        row.id: row
        for row in session.scalars(select(MenuItem).where(MenuItem.id.in_(ids))).all()
    }
    positions: list[tuple[MenuItem, int]] = []
    for item in payload.items:
        menu_item = menu.get(item.id)
        if menu_item is None or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"позиция {item.id} не найдена")
        if not menu_item.is_available:
            raise HTTPException(status.HTTP_409_CONFLICT, f"«{menu_item.name}» закончилась")
        positions.append((menu_item, item.count))

    subtotal_kop = sum(menu_item.price_kop * count for menu_item, count in positions)

    point = (address.lat, address.lon)
    now = now_utc()
    try:
        delivery = pricing.calc_delivery(session, restaurant, point, subtotal_kop, now)
    except pricing.DeliveryUnavailable as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    cart_total_kop = subtotal_kop + delivery.total_kop

    discount_kop = 0
    promo = promo_service.find_promo(session, payload.promo)
    if payload.promo:
        check = promo_service.validate_promo(session, promo, user.id, cart_total_kop, now)
        if not check.ok:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"промокод: {check.reason}")
        discount_kop = check.discount_kop

    total_kop = clamp_non_negative(cart_total_kop - discount_kop)

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

    for menu_item, count in positions:
        session.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                name=menu_item.name,
                price_kop=menu_item.price_kop,
                qty=count,
            )
        )

    if promo is not None and discount_kop > 0:
        session.add(
            PromoUsage(
                promo_code=promo.code,
                user_id=user.id,
                order_id=order.id,
                discount_kop=discount_kop,
            )
        )

    try:
        hold = payments_service.create_hold(order.id, total_kop, user.phone)
    except payments_service.ProviderError as error:
        session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"платёж не прошёл: {error}") from error

    session.add(
        Payment(
            order_id=order.id,
            provider_id=str(hold.get("id", "")),
            amount_kop=total_kop,
            status="hold",
        )
    )
    session.commit()
    logger.info("legacy.checkout", extra={"order_id": order.id, "total_kop": total_kop})

    return CheckoutResponseV1(
        id=order.id,
        state=OrderStatus(order.status).value,
        amount=str(kop_to_rub(order.total_kop)),
        delivery_price=str(kop_to_rub(order.delivery_kop)),
        promo_discount=str(kop_to_rub(order.discount_kop)),
        eta_minutes=pricing.eta_minutes(restaurant, delivery.distance_m),
    )
