"""Расчёт стоимости доставки.

Формула:

    база + расстояние + ночная наценка + surge

`база` и `расстояние` обнуляются, если корзина дотянула до порога бесплатной
доставки (`free_delivery_from_kop`). Ночная наценка и surge при этом остаются:
это компенсация курьеру, а не наша маржа.

Стоимость еды (`subtotal_kop`) в расчёт доставки не входит, она нужна только
чтобы понять, сработал ли порог бесплатной доставки.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Restaurant
from app.services import surge as surge_service
from app.services.zones import Point, haversine_m
from app.utils.money import round_kop
from app.utils.timeutil import is_night

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeliveryPrice:
    """Разложение стоимости доставки по составляющим.

    Фронт показывает разбивку в чеке, поэтому важны все поля, а не только
    `total_kop`.
    """

    base_kop: int
    distance_kop: int
    surge_kop: int
    night_kop: int
    total_kop: int
    free_applied: bool
    distance_m: int = 0

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "base_kop": self.base_kop,
            "distance_kop": self.distance_kop,
            "surge_kop": self.surge_kop,
            "night_kop": self.night_kop,
            "total_kop": self.total_kop,
            "free_applied": self.free_applied,
            "distance_m": self.distance_m,
        }


class DeliveryUnavailable(RuntimeError):
    """Адрес вне радиуса доставки ресторана."""

    def __init__(self, distance_m: float) -> None:
        super().__init__(f"адрес в {int(distance_m)} м от ресторана, это вне радиуса")
        self.distance_m = int(distance_m)


def distance_surcharge_kop(distance_m: float) -> int:
    """Наценка за расстояние: каждый начатый километр сверх бесплатных."""
    extra_m = distance_m - settings.free_distance_m
    if extra_m <= 0:
        return 0
    extra_km = math.ceil(extra_m / 1000)
    return extra_km * settings.price_per_km_kop


def calc_delivery(
    session: Session,
    restaurant: Restaurant,
    point: Point,
    subtotal_kop: int,
    now: datetime,
) -> DeliveryPrice:
    """Посчитать доставку из ресторана в точку.

    :raises DeliveryUnavailable: если точка дальше `max_delivery_radius_m`.
    """
    distance_m = haversine_m((restaurant.lat, restaurant.lon), point)
    if distance_m > settings.max_delivery_radius_m:
        raise DeliveryUnavailable(distance_m)

    base_kop = settings.base_delivery_kop
    distance_kop = distance_surcharge_kop(distance_m)
    ride_kop = base_kop + distance_kop

    night_kop = round_kop(ride_kop * settings.night_rate) if is_night(now) else 0

    multiplier = surge_service.multiplier_for_point(session, point)
    surge_kop = round_kop(ride_kop * (multiplier - 1.0)) if multiplier > 1.0 else 0

    free_applied = subtotal_kop >= settings.free_delivery_from_kop
    total_kop = night_kop + surge_kop if free_applied else ride_kop + night_kop + surge_kop

    price = DeliveryPrice(
        base_kop=base_kop,
        distance_kop=distance_kop,
        surge_kop=surge_kop,
        night_kop=night_kop,
        total_kop=total_kop,
        free_applied=free_applied,
        distance_m=int(distance_m),
    )
    logger.debug(
        "delivery.calc",
        extra={"restaurant_id": restaurant.id, "distance_m": price.distance_m, "k": multiplier},
    )
    return price


def eta_minutes(restaurant: Restaurant, distance_m: float) -> int:
    """Грубая оценка времени доставки: готовка + дорога на 15 км/ч."""
    ride_minutes = math.ceil(distance_m / 250)
    return restaurant.cook_minutes + ride_minutes
