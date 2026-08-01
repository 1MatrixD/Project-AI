"""Админка: отчёты, промокоды, зоны доставки.

Доступ только с флагом `is_admin`, отдельного SSO у нас нет.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import AdminUser, SessionDep
from app.models import Promo, Zone
from app.schemas import (
    CourierReportRow,
    PromoIn,
    PromoRead,
    ZoneIn,
    ZonePreviewIn,
    ZonePreviewOut,
    ZoneRead,
)
from app.services import promo as promo_service
from app.services import reports, surge
from app.services import zones as zones_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/reports/couriers", response_model=list[CourierReportRow])
def couriers_report(
    session: SessionDep,
    admin: AdminUser,
    day: date = Query(alias="date"),
) -> list[dict]:
    """Отчёт по курьерам за операционный день."""
    logger.info("admin.report", extra={"admin_id": admin.id, "day": str(day)})
    return reports.courier_day(session, day)


@router.get("/promos", response_model=list[PromoRead])
def list_promos(session: SessionDep, admin: AdminUser) -> list[PromoRead]:
    """Все промокоды со счётчиком использований."""
    promos = session.scalars(select(Promo).order_by(Promo.id.desc())).all()
    result: list[PromoRead] = []
    for promo in promos:
        row = PromoRead.model_validate(promo)
        row.used_total = promo_service.usage_count(session, promo.code)
        result.append(row)
    return result


@router.post("/promos", response_model=PromoRead, status_code=status.HTTP_201_CREATED)
def create_promo(payload: PromoIn, session: SessionDep, admin: AdminUser) -> PromoRead:
    """Завести промокод. Код нормализуем в верхний регистр."""
    code = payload.code.strip().upper()
    if session.scalar(select(Promo).where(Promo.code == code)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "такой промокод уже есть")
    if payload.kind == "percent" and payload.value > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "скидка больше 100%")

    promo = Promo(**{**payload.model_dump(), "code": code})
    session.add(promo)
    session.commit()
    logger.info("promo.created", extra={"code": code, "admin_id": admin.id})
    return PromoRead.model_validate(promo)


@router.get("/zones", response_model=list[ZoneRead])
def list_zones(session: SessionDep, admin: AdminUser) -> list[Zone]:
    """Список зон доставки."""
    return list(session.scalars(select(Zone).order_by(Zone.name)).all())


@router.post("/zones", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
def create_zone(payload: ZoneIn, session: SessionDep, admin: AdminUser) -> Zone:
    """Создать зону. Bbox считаем здесь, руками его никто не задаёт."""
    if session.scalar(select(Zone).where(Zone.name == payload.name)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "зона с таким именем уже есть")

    zone = Zone(
        name=payload.name,
        polygon=payload.polygon,
        bbox=zones_service.bbox_of(payload.polygon),
        is_active=payload.is_active,
    )
    session.add(zone)
    session.commit()
    surge.reset_cache(zone.id)
    logger.info("zone.created", extra={"zone_id": zone.id, "admin_id": admin.id})
    return zone


@router.post("/zones/preview", response_model=ZonePreviewOut)
def preview_zone(payload: ZonePreviewIn, admin: AdminUser) -> ZonePreviewOut:
    """Проверить набор точек на вхождение в нарисованный полигон.

    Админка дёргает это, пока оператор двигает вершины на карте: показывает,
    какие контрольные адреса попадают в зону, а какие остались снаружи.
    """
    bbox = zones_service.bbox_of(payload.polygon)
    inside = [
        zones_service.point_in_polygon(payload.polygon, (point[0], point[1]))
        for point in payload.points
    ]
    return ZonePreviewOut(bbox=bbox, inside=inside)


@router.post("/zones/{zone_id}/toggle", response_model=ZoneRead)
def toggle_zone(zone_id: int, session: SessionDep, admin: AdminUser) -> Zone:
    """Включить/выключить зону."""
    zone = session.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "зона не найдена")
    zone.is_active = not zone.is_active
    session.commit()
    surge.reset_cache(zone.id)
    return zone
