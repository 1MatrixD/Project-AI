"""Клиент платёжного провайдера.

Схема работы: при оформлении заказа ставим холд на сумму, после подтверждения
рестораном — списываем (capture), при отмене — возвращаем (refund).

Провайдер иногда отдаёт 502/504 на ровном месте, поэтому идемпотентные
запросы (`capture`, `refund`) повторяем с линейной паузой. `create_hold`
повторяем тоже — на стороне провайдера он дедуплицируется по `order_id`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Провайдер вернул ошибку или не ответил."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.payments_base_url,
        timeout=settings.payments_timeout_s,
        headers={
            "Authorization": f"Bearer {settings.payments_api_key}",
            "Content-Type": "application/json",
        },
    )


def _request(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST/GET с ретраями. Последняя ошибка прокидывается как ProviderError."""
    last_error: Exception | None = None
    for attempt in range(1, settings.payments_retries + 1):
        try:
            with _client() as client:
                response = client.request(method, path, json=payload)
            if response.status_code >= 500:
                raise ProviderError(f"провайдер вернул {response.status_code}", response.status_code)
            if response.status_code >= 400:
                # Клиентские ошибки не ретраим: сумма/карта/лимит не изменятся.
                detail = response.json().get("message", response.text)
                raise ProviderError(detail, response.status_code)
            return response.json()
        except (httpx.TransportError, ProviderError) as error:
            if isinstance(error, ProviderError) and error.status_code and error.status_code < 500:
                raise
            last_error = error
            logger.warning(
                "payments.retry",
                extra={"path": path, "attempt": attempt, "error": str(error)},
            )
            if attempt < settings.payments_retries:
                time.sleep(0.3 * attempt)
    raise ProviderError(f"не достучались до провайдера: {last_error}")


def create_hold(order_id: int, amount_kop: int, user_phone: str) -> dict[str, Any]:
    """Поставить холд на сумму заказа. Возвращает объект платежа провайдера."""
    payload = {
        "order_id": str(order_id),
        "amount": {"value": amount_kop, "currency": "RUB"},
        "capture": False,
        "customer": {"phone": user_phone},
        "description": f"Заказ №{order_id} в Скороходе",
    }
    data = _request("POST", "/payments", payload)
    logger.info("payments.hold", extra={"order_id": order_id, "payment_id": data.get("id")})
    return data


def capture(provider_id: str, amount_kop: int) -> dict[str, Any]:
    """Списать ранее захолдированную сумму."""
    payload = {"amount": {"value": amount_kop, "currency": "RUB"}}
    data = _request("POST", f"/payments/{provider_id}/capture", payload)
    logger.info("payments.capture", extra={"payment_id": provider_id, "amount_kop": amount_kop})
    return data


def refund(provider_id: str, amount_kop: int, reason: str = "order_cancelled") -> dict[str, Any]:
    """Вернуть деньги целиком или частично."""
    payload = {
        "payment_id": provider_id,
        "amount": {"value": amount_kop, "currency": "RUB"},
        "description": reason,
    }
    data = _request("POST", "/refunds", payload)
    logger.info("payments.refund", extra={"payment_id": provider_id, "amount_kop": amount_kop})
    return data


def fetch(provider_id: str) -> dict[str, Any]:
    """Состояние платежа на стороне провайдера. Нужно для сверки."""
    return _request("GET", f"/payments/{provider_id}", {})
