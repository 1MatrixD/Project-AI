"""Статусы заказа и переходы между ними.

Менять `order.status` напрямую нельзя: история переходов и уведомления
живут в `set_status()`.
"""

from __future__ import annotations

import logging
from enum import Enum

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """Жизненный цикл заказа."""

    created = "created"
    paid = "paid"
    cooking = "cooking"
    courier_assigned = "courier_assigned"
    at_restaurant = "at_restaurant"
    picked_up = "picked_up"
    delivering = "delivering"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"


#: Терминальные статусы — из них выхода нет.
TERMINAL: frozenset[OrderStatus] = frozenset(
    {OrderStatus.delivered, OrderStatus.cancelled, OrderStatus.refunded}
)

#: Статусы, в которых заказ считается «в работе» у курьера.
ACTIVE_FOR_COURIER: tuple[OrderStatus, ...] = (
    OrderStatus.courier_assigned,
    OrderStatus.at_restaurant,
    OrderStatus.picked_up,
    OrderStatus.delivering,
)

ALLOWED_TRANSITIONS: dict[OrderStatus, tuple[OrderStatus, ...]] = {
    OrderStatus.created: (OrderStatus.paid, OrderStatus.cancelled),
    OrderStatus.paid: (OrderStatus.cooking, OrderStatus.cancelled, OrderStatus.refunded),
    OrderStatus.cooking: (
        OrderStatus.courier_assigned,
        OrderStatus.cancelled,
        OrderStatus.refunded,
    ),
    OrderStatus.courier_assigned: (
        OrderStatus.at_restaurant,
        OrderStatus.cancelled,
        OrderStatus.refunded,
    ),
    OrderStatus.at_restaurant: (OrderStatus.picked_up, OrderStatus.refunded),
    OrderStatus.picked_up: (OrderStatus.delivering, OrderStatus.refunded),
    OrderStatus.delivering: (OrderStatus.delivered, OrderStatus.refunded),
    OrderStatus.delivered: (OrderStatus.refunded,),
    OrderStatus.cancelled: (),
    OrderStatus.refunded: (),
}


class InvalidTransition(RuntimeError):
    """Попытка перевести заказ в статус, недостижимый из текущего."""

    def __init__(self, current: OrderStatus, new: OrderStatus) -> None:
        super().__init__(f"переход {current.value} -> {new.value} запрещён")
        self.current = current
        self.new = new


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    """Разрешён ли переход `current -> new`."""
    return new in ALLOWED_TRANSITIONS.get(current, ())


def set_status(session: Session, order, new: OrderStatus, actor: str) -> None:
    """Перевести заказ в новый статус.

    Пишет строку в `status_history` и дёргает уведомления. `actor` — кто
    инициировал переход: `user:12`, `courier:4`, `worker:assign`, `webhook`.

    Идемпотентен: повторный перевод в тот же статус ничего не делает.
    """
    # Ленивые импорты: models и notifications сами тянут статусы.
    from app.models import StatusHistory
    from app.services import notifications
    from app.utils.timeutil import now_utc

    current = OrderStatus(order.status)
    if current == new:
        return
    if not can_transition(current, new):
        raise InvalidTransition(current, new)

    order.status = new
    if new == OrderStatus.delivered:
        order.delivered_at = now_utc()

    session.add(
        StatusHistory(
            order_id=order.id,
            from_status=current,
            to_status=new,
            actor=actor,
            created_at=now_utc(),
        )
    )
    session.flush()
    logger.info(
        "order.status",
        extra={"order_id": order.id, "from": current.value, "to": new.value, "actor": actor},
    )
    notifications.notify_status(order, new)
