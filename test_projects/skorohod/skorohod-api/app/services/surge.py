"""Динамический коэффициент спроса (surge).

Считаем по зоне: сколько заказов «в работе» приходится на одного курьера
на смене. Пересчёт дорогой (два count по orders), поэтому держим in-memory
кэш с TTL 60 секунд — на инстанс, синхронизация между подами не нужна,
расхождение в пределах минуты допустимо.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, Shift
from app.services import zones as zones_service
from app.services.statuses import ACTIVE_FOR_COURIER

logger = logging.getLogger(__name__)

CACHE_TTL_S = 60.0

#: zone_id -> (коэффициент, момент протухания)
_cache: dict[int, tuple[float, float]] = {}


def _load_multiplier(session: Session, zone_id: int) -> float:
    """Пересчитать коэффициент по текущей загрузке зоны."""
    couriers_on_shift = session.scalar(
        select(func.count(Shift.id)).where(
            Shift.zone_id == zone_id,
            Shift.ended_at.is_(None),
        )
    )
    if not couriers_on_shift:
        # Курьеров нет — накручивать цену бессмысленно, заказ всё равно
        # повиснет в очереди диспетчера.
        return 1.0

    active_orders = session.scalar(
        select(func.count(Order.id)).where(Order.status.in_(ACTIVE_FOR_COURIER))
    )
    load = (active_orders or 0) / couriers_on_shift
    if load <= 1.0:
        return 1.0
    multiplier = 1.0 + (load - 1.0) * 0.25
    return min(round(multiplier, 2), settings.surge_max)


def zone_multiplier(session: Session, zone_id: int) -> float:
    """Коэффициент для зоны с учётом кэша."""
    now = time.monotonic()
    cached = _cache.get(zone_id)
    if cached and cached[1] > now:
        return cached[0]

    multiplier = _load_multiplier(session, zone_id)
    _cache[zone_id] = (multiplier, now + CACHE_TTL_S)
    logger.debug("surge.recalc", extra={"zone_id": zone_id, "k": multiplier})
    return multiplier


def multiplier_for_point(session: Session, point: tuple[float, float]) -> float:
    """Коэффициент для точки доставки.

    Если surge выключен флагом или точка вне известных зон — 1.0.
    """
    if not settings.surge_enabled:
        return 1.0
    zone = zones_service.zone_for_point(session, point)
    if zone is None:
        return 1.0
    return zone_multiplier(session, zone.id)


def reset_cache(zone_id: int | None = None) -> None:
    """Сбросить кэш. Дёргается админкой после правки зоны."""
    if zone_id is None:
        _cache.clear()
    else:
        _cache.pop(zone_id, None)
