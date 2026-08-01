"""Отчёты для админки.

Все отчёты строятся «за операционный день» — тот же московский день, по
которому живут смены курьеров.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Courier, Order, OrderItem, Restaurant, Shift
from app.services.statuses import OrderStatus
from app.utils.timeutil import day_bounds_utc, minutes_between, now_utc

logger = logging.getLogger(__name__)


def courier_day(session: Session, day: date) -> list[dict[str, Any]]:
    """Сводка по курьерам за день.

    На курьера отдаём: сколько заказов взял, сколько довёз, на какую сумму
    и сколько минут отработал по сменам этого дня.
    """
    rows = session.execute(
        select(
            Order.courier_id,
            func.count(Order.id).label("orders"),
            func.sum(
                case((Order.status != OrderStatus.cancelled, 1), else_=0)
            ).label("delivered"),
            func.coalesce(func.sum(Order.total_kop), 0).label("revenue_kop"),
        )
        .where(
            Order.courier_id.is_not(None),
            func.date(Order.created_at) == day,
        )
        .group_by(Order.courier_id)
    ).all()

    shift_minutes = _shift_minutes(session, day)
    couriers = {
        courier.id: courier
        for courier in session.scalars(select(Courier)).all()
    }

    report: list[dict[str, Any]] = []
    for row in rows:
        courier = couriers.get(row.courier_id)
        report.append(
            {
                "courier_id": row.courier_id,
                "name": courier.name if courier else "—",
                "orders": int(row.orders or 0),
                "delivered": int(row.delivered or 0),
                "revenue_kop": int(row.revenue_kop or 0),
                "shift_minutes": shift_minutes.get(row.courier_id, 0),
            }
        )
    report.sort(key=lambda item: item["delivered"], reverse=True)
    logger.info("report.courier_day", extra={"day": str(day), "rows": len(report)})
    return report


def _shift_minutes(session: Session, day: date) -> dict[int, int]:
    """Отработанные минуты по сменам, отнесённым к этому дню."""
    shifts = session.scalars(select(Shift).where(Shift.local_date == day)).all()
    result: dict[int, int] = {}
    for shift in shifts:
        finished_at = shift.ended_at or now_utc()
        result[shift.courier_id] = result.get(shift.courier_id, 0) + minutes_between(
            shift.started_at, finished_at
        )
    return result


def restaurant_day(session: Session, day: date) -> list[dict[str, Any]]:
    """Сводка по ресторанам за день: заказы, выручка, средний чек, позиции."""
    start_utc, end_utc = day_bounds_utc(day)
    rows = session.execute(
        select(
            Order.restaurant_id,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.subtotal_kop), 0).label("food_kop"),
        )
        .where(
            Order.created_at >= start_utc,
            Order.created_at < end_utc,
            Order.status == OrderStatus.delivered,
        )
        .group_by(Order.restaurant_id)
    ).all()

    names = {r.id: r.name for r in session.scalars(select(Restaurant)).all()}
    items_count = dict(
        session.execute(
            select(Order.restaurant_id, func.coalesce(func.sum(OrderItem.qty), 0))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.created_at >= start_utc, Order.created_at < end_utc)
            .group_by(Order.restaurant_id)
        ).all()
    )

    report = []
    for row in rows:
        orders = int(row.orders or 0)
        food_kop = int(row.food_kop or 0)
        report.append(
            {
                "restaurant_id": row.restaurant_id,
                "name": names.get(row.restaurant_id, "—"),
                "orders": orders,
                "food_kop": food_kop,
                "avg_check_kop": food_kop // orders if orders else 0,
                "items": int(items_count.get(row.restaurant_id, 0)),
            }
        )
    report.sort(key=lambda item: item["food_kop"], reverse=True)
    return report
