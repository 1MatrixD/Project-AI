"""Тесты проверки промокодов.

Промокоды без лимитов (`per_user_limit`/`total_limit`) не ходят в базу за
счётчиками, поэтому сессию можно не поднимать.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import Promo
from app.services import promo as promo_service
from app.utils.timeutil import MSK

NOW = datetime(2026, 3, 12, 13, 40, tzinfo=MSK)

#: сумма заказа заведомо выше любых порогов в тестах
BIG_CART_KOP = 500_000


def make_promo(**overrides) -> Promo:
    """Промокод с разумными значениями по умолчанию."""
    defaults = dict(
        code="VESNA",
        kind="percent",
        value=10,
        min_total_kop=100_000,
        max_discount_kop=None,
        per_user_limit=None,
        total_limit=None,
        active_from=None,
        active_until=None,
        is_active=True,
    )
    defaults.update(overrides)
    return Promo(**defaults)


def test_percent_promo_gives_discount() -> None:
    """Процентный промокод считает скидку от суммы заказа."""
    promo = make_promo(kind="percent", value=10)

    check = promo_service.validate_promo(None, promo, user_id=1, cart_total_kop=BIG_CART_KOP, now=NOW)

    assert check.ok is True
    assert check.reason is None
    assert check.discount_kop == BIG_CART_KOP // 10


def test_percent_promo_respects_cap() -> None:
    """Потолок скидки ограничивает процентный промокод."""
    promo = make_promo(kind="percent", value=50, max_discount_kop=30_000)

    check = promo_service.validate_promo(None, promo, user_id=1, cart_total_kop=BIG_CART_KOP, now=NOW)

    assert check.ok is True
    assert check.discount_kop == 30_000


def test_fixed_promo_gives_exact_amount() -> None:
    """Фиксированный промокод даёт ровно свою сумму в копейках."""
    promo = make_promo(kind="fixed", value=15_000)

    check = promo_service.validate_promo(None, promo, user_id=7, cart_total_kop=BIG_CART_KOP, now=NOW)

    assert check.ok is True
    assert check.discount_kop == 15_000


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"is_active": False}, "inactive"),
        ({"active_from": NOW + timedelta(days=1)}, "not_started"),
        ({"active_until": NOW - timedelta(days=1)}, "expired"),
    ],
)
def test_promo_window_and_flags(overrides: dict, reason: str) -> None:
    """Выключенный и просроченный промокод отклоняются с понятной причиной."""
    promo = make_promo(**overrides)

    check = promo_service.validate_promo(None, promo, user_id=1, cart_total_kop=BIG_CART_KOP, now=NOW)

    assert check.ok is False
    assert check.discount_kop == 0
    assert check.reason == reason


def test_unknown_promo_is_not_found() -> None:
    """Несуществующий код — отдельная причина отказа, фронт покажет свой текст."""
    check = promo_service.validate_promo(None, None, user_id=1, cart_total_kop=BIG_CART_KOP, now=NOW)

    assert check.ok is False
    assert check.reason == "not_found"
