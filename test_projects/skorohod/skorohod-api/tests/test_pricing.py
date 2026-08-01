"""Тесты расчёта доставки.

База не нужна: surge на время тестов выключаем, тогда `calc_delivery` в базу
не ходит и сессию можно не поднимать.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import pricing
from app.utils.timeutil import MSK

#: обычный будний день, 13:40 по Москве — ни ночи, ни выходных
DAYTIME = datetime(2026, 3, 12, 13, 40, tzinfo=MSK)

#: примерно центр Москвы
RESTAURANT_POINT = (55.7520, 37.6175)


@pytest.fixture(autouse=True)
def no_surge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surge выключен: тестируем чистую формулу без коэффициента спроса."""
    monkeypatch.setattr(settings, "surge_enabled", False)


@pytest.fixture()
def restaurant() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="Пельменная №1",
        lat=RESTAURANT_POINT[0],
        lon=RESTAURANT_POINT[1],
        cook_minutes=20,
    )


def point_north(meters: float) -> tuple[float, float]:
    """Точка ровно на `meters` севернее ресторана."""
    return RESTAURANT_POINT[0] + meters / 111_320.0, RESTAURANT_POINT[1]


def test_short_distance_costs_base_only(restaurant: SimpleNamespace) -> None:
    """В пределах бесплатного радиуса платим только базовую стоимость."""
    price = pricing.calc_delivery(None, restaurant, point_north(1200), 90_000, DAYTIME)

    assert price.base_kop == settings.base_delivery_kop
    assert price.distance_kop == 0
    assert price.night_kop == 0
    assert price.surge_kop == 0
    assert price.free_applied is False
    assert price.total_kop == settings.base_delivery_kop


def test_distance_surcharge_per_started_km(restaurant: SimpleNamespace) -> None:
    """За каждый начатый километр сверх бесплатных берём фиксированную сумму."""
    price = pricing.calc_delivery(None, restaurant, point_north(5100), 90_000, DAYTIME)

    # 5100 - 3000 = 2100 м сверх бесплатных, это три начатых километра
    assert price.distance_kop == 3 * settings.price_per_km_kop
    assert price.total_kop == settings.base_delivery_kop + price.distance_kop


def test_free_delivery_above_threshold(restaurant: SimpleNamespace) -> None:
    """Корзина от порога — доставка бесплатная, даже если ехать далеко."""
    price = pricing.calc_delivery(
        None, restaurant, point_north(6000), settings.free_delivery_from_kop, DAYTIME
    )

    assert price.free_applied is True
    assert price.total_kop == 0
    # разбивку всё равно показываем пользователю: видно, сколько он сэкономил
    assert price.base_kop == settings.base_delivery_kop
    assert price.distance_kop > 0


def test_too_far_is_rejected(restaurant: SimpleNamespace) -> None:
    """Дальше максимального радиуса не возим."""
    far = point_north(settings.max_delivery_radius_m + 500)

    with pytest.raises(pricing.DeliveryUnavailable) as error:
        pricing.calc_delivery(None, restaurant, far, 90_000, DAYTIME)

    assert error.value.distance_m > settings.max_delivery_radius_m
