"""Уведомления пользователю о смене статуса заказа.

Пока это СМС через внешний шлюз; пуши появятся, когда мобилка научится их
принимать. Не все статусы стоят сообщения — служебные переходы человеку
неинтересны.

Дедуп: на один заказ один статус отправляется ровно один раз, даже если
`set_status` дёрнули повторно (ретрай воркера, двойной вебхук).
"""

from __future__ import annotations

import logging

from app.config import settings
from app.services.statuses import OrderStatus
from app.utils.money import fmt_rub

logger = logging.getLogger(__name__)

TEMPLATES: dict[OrderStatus, str] = {
    OrderStatus.paid: "Заказ №{order_id} принят, {total}. Ресторан начал готовить.",
    OrderStatus.cooking: "Заказ №{order_id} готовится. Мы уже ищем курьера.",
    OrderStatus.courier_assigned: "Курьер назначен на заказ №{order_id} и едет в ресторан.",
    OrderStatus.picked_up: "Курьер забрал заказ №{order_id} и выехал к вам.",
    OrderStatus.delivering: "Курьер с заказом №{order_id} рядом, встречайте.",
    OrderStatus.delivered: "Заказ №{order_id} доставлен. Спасибо, что выбрали Скороход!",
    OrderStatus.cancelled: "Заказ №{order_id} отменён. Деньги вернутся на карту.",
    OrderStatus.refunded: "По заказу №{order_id} оформлен возврат {total}.",
}

#: (order_id, status) уже отправленных сообщений. Живёт в памяти процесса:
#: перезапуск раз в сутки, дубль после деплоя переживём.
_sent: set[tuple[int, str]] = set()


def render(order, status: OrderStatus) -> str | None:
    """Текст уведомления или None, если по этому статусу мы молчим."""
    template = TEMPLATES.get(status)
    if template is None:
        return None
    return template.format(order_id=order.id, total=fmt_rub(order.total_kop))


def notify_status(order, status: OrderStatus) -> bool:
    """Отправить уведомление о переходе заказа в статус.

    Возвращает True, если сообщение действительно ушло.
    """
    key = (order.id, status.value)
    if key in _sent:
        logger.debug("notify.skip_duplicate", extra={"order_id": order.id, "status": status.value})
        return False

    text = render(order, status)
    if text is None:
        return False

    _sent.add(key)
    return _send_sms(order, text)


def _send_sms(order, text: str) -> bool:
    """Отправка в шлюз.

    Шлюз недоступен -> логируем и живём дальше: уведомление не настолько
    важно, чтобы ронять транзакцию заказа.
    """
    if settings.sms_token == "change-me":
        logger.info("notify.dry_run", extra={"order_id": order.id, "text": text})
        return False
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            client.post(
                "https://sms-gate.example.ru/send",
                json={"sender": settings.sms_sender, "order_id": order.id, "text": text},
                headers={"Authorization": f"Bearer {settings.sms_token}"},
            )
    except Exception as error:  # noqa: BLE001 - шлюз не должен ронять заказ
        logger.warning("notify.failed", extra={"order_id": order.id, "error": str(error)})
        return False
    return True


def forget(order_id: int) -> None:
    """Забыть историю отправок по заказу. Нужно тестам и ручному ресенду."""
    for key in [key for key in _sent if key[0] == order_id]:
        _sent.discard(key)
