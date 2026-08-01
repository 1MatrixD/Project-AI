"""Платежи: вебхук провайдера и ручной возврат из админки.

Провайдер шлёт события подписанными: `X-Signature` — hex HMAC-SHA256 от сырого
тела запроса на секрете `PAYMENTS_WEBHOOK_SECRET`.

Типы событий: `payment.succeeded`, `payment.failed`, `refund.succeeded`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select

from app.config import settings
from app.db import get_session
from app.deps import AdminUser, SessionDep
from app.models import Order, Payment
from app.schemas import WebhookIn
from app.services import payments as payments_service
from app.services.statuses import InvalidTransition, OrderStatus, set_status
from app.utils import idempotency
from app.utils.timeutil import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["payments"])


def _check_signature(raw_body: bytes, signature: str | None) -> None:
    """Сверить подпись тела запроса."""
    if not signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нет подписи")
    expected = hmac.new(
        settings.payments_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning("webhook.bad_signature")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "подпись не сошлась")


def _payment_for(session: SessionDep, order_id: int, provider_id: str) -> Payment:
    payment = session.scalar(
        select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc())
    )
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"платёж по заказу {order_id} не найден")
    if not payment.provider_id:
        payment.provider_id = provider_id
    return payment


@router.post("/webhooks/payments")
async def payments_webhook(request: Request) -> dict[str, bool]:
    """Приём событий платёжного провайдера."""
    raw_body = await request.body()
    _check_signature(raw_body, request.headers.get("X-Signature"))

    try:
        payload = WebhookIn.model_validate_json(raw_body)
    except ValidationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "неизвестный формат события") from error

    session_gen = get_session()
    session = next(session_gen)
    try:
        order = session.get(Order, payload.object.order_id)
        if order is None:
            logger.warning("webhook.unknown_order", extra={"order_id": payload.object.order_id})
            return {"ok": True}

        if payload.type == "payment.succeeded":
            payment = _payment_for(session, order.id, payload.object.payment_id)
            payments_service.capture(payment.provider_id, payload.object.amount_kop)
            payment.status = "captured"
            payment.captured_at = now_utc()
            try:
                set_status(session, order, OrderStatus.paid, actor="webhook")
            except InvalidTransition as error:
                logger.info("webhook.skip_transition", extra={"order_id": order.id, "e": str(error)})
            session.commit()

        elif payload.type == "refund.succeeded":
            if idempotency.already_processed(session, payload.event_id):
                return {"ok": True}
            payment = _payment_for(session, order.id, payload.object.payment_id)
            payment.status = "refunded"
            try:
                set_status(session, order, OrderStatus.refunded, actor="webhook")
            except InvalidTransition as error:
                logger.info("webhook.skip_transition", extra={"order_id": order.id, "e": str(error)})
            idempotency.mark_processed(session, payload.event_id, payload.type)
            session.commit()

        elif payload.type == "payment.failed":
            if idempotency.already_processed(session, payload.event_id):
                return {"ok": True}
            payment = _payment_for(session, order.id, payload.object.payment_id)
            payment.status = "failed"
            try:
                set_status(session, order, OrderStatus.cancelled, actor="webhook")
            except InvalidTransition as error:
                logger.info("webhook.skip_transition", extra={"order_id": order.id, "e": str(error)})
            idempotency.mark_processed(session, payload.event_id, payload.type)
            session.commit()

        else:
            logger.info("webhook.ignored", extra={"type": payload.type})
    finally:
        session_gen.close()

    return {"ok": True}


@router.post("/admin/payments/{order_id}/refund")
def manual_refund(
    order_id: int,
    session: SessionDep,
    admin: AdminUser,
    amount_kop: int | None = None,
) -> dict[str, int | str]:
    """Ручной возврат из админки: целиком или частично.

    Провайдер после успешного возврата пришлёт `refund.succeeded`, там заказ
    и переедет в статус `refunded`.
    """
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "заказ не найден")

    payment = session.scalar(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc())
    )
    if payment is None or payment.status not in {"hold", "captured"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "по заказу нечего возвращать")

    amount = amount_kop or payment.amount_kop
    if amount <= 0 or amount > payment.amount_kop:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "некорректная сумма возврата")

    try:
        result = payments_service.refund(payment.provider_id, amount, reason="manual")
    except payments_service.ProviderError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    logger.info(
        "payments.manual_refund",
        extra={"order_id": order.id, "amount_kop": amount, "admin_id": admin.id},
    )
    session.commit()
    return {"order_id": order.id, "amount_kop": amount, "refund_id": str(result.get("id", ""))}
