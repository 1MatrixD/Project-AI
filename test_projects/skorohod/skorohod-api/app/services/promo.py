"""Промокоды: проверка и применение.

Виды промокодов:

* `percent` — `value` процентов от суммы, с потолком `max_discount_kop`;
* `fixed` — `value` копеек скидки.

Промокод не может сделать заказ бесплатным: скидка ограничена суммой, к которой
применяется.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Promo, PromoUsage
from app.utils.money import clamp_non_negative, percent_of
from app.utils.timeutil import ensure_aware

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PromoCheck:
    """Результат проверки промокода.

    `reason` заполняется только при `ok is False`, фронт по нему подбирает
    текст ошибки: not_found, inactive, not_started, expired, min_total,
    per_user_limit, total_limit.
    """

    ok: bool
    discount_kop: int = 0
    reason: str | None = None

    @classmethod
    def fail(cls, reason: str) -> "PromoCheck":
        return cls(ok=False, discount_kop=0, reason=reason)


def usage_count(session: Session, code: str, user_id: int | None = None) -> int:
    """Сколько раз промокод уже применяли.

    С `user_id` — сколько раз применял конкретный пользователь.
    """
    stmt = select(func.count(PromoUsage.id)).where(PromoUsage.promo_code == code)
    if user_id is not None:
        stmt = stmt.where(PromoUsage.user_id == user_id)
    return session.scalar(stmt) or 0


def apply_promo(promo: Promo, cart_total_kop: int) -> int:
    """Размер скидки в копейках для данной суммы."""
    if promo.kind == "percent":
        discount = percent_of(cart_total_kop, promo.value)
        if promo.max_discount_kop is not None:
            discount = min(discount, promo.max_discount_kop)
    else:
        discount = int(promo.value)
    return clamp_non_negative(min(discount, cart_total_kop))


def validate_promo(
    session: Session,
    promo: Promo | None,
    user_id: int,
    cart_total_kop: int,
    now: datetime,
) -> PromoCheck:
    """Проверить промокод и посчитать скидку.

    `cart_total_kop` — сумма заказа, к которой применяется промокод и с которой
    сравнивается минимальный порог `min_total_kop`.
    """
    if promo is None:
        return PromoCheck.fail("not_found")
    if not promo.is_active:
        return PromoCheck.fail("inactive")

    moment = ensure_aware(now)
    if promo.active_from is not None and moment < ensure_aware(promo.active_from):
        return PromoCheck.fail("not_started")
    if promo.active_until is not None and moment > ensure_aware(promo.active_until):
        return PromoCheck.fail("expired")

    if cart_total_kop < promo.min_total_kop:
        return PromoCheck.fail("min_total")

    if promo.per_user_limit is not None:
        if usage_count(session, promo.code, user_id=user_id) >= promo.per_user_limit:
            return PromoCheck.fail("per_user_limit")
    if promo.total_limit is not None:
        if usage_count(session, promo.code) >= promo.total_limit:
            return PromoCheck.fail("total_limit")

    discount = apply_promo(promo, cart_total_kop)
    if discount <= 0:
        return PromoCheck.fail("min_total")

    logger.info(
        "promo.ok",
        extra={"code": promo.code, "user_id": user_id, "discount_kop": discount},
    )
    return PromoCheck(ok=True, discount_kop=discount)


def find_promo(session: Session, code: str | None) -> Promo | None:
    """Промокод по коду, регистр не важен."""
    if not code:
        return None
    normalized = code.strip().upper()
    return session.scalar(select(Promo).where(Promo.code == normalized))
