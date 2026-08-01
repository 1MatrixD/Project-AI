"""Трекинг заказа через Server-Sent Events.

Фронт открывает `EventSource` и слушает три типа событий:

* `status` — новый статус заказа;
* `courier_position` — координаты курьера (пока он в работе);
* `heartbeat` — пустое событие раз в 15 секунд, чтобы nginx и мобильные
  операторы не рубили «молчащее» соединение.

EventSource не умеет слать заголовки, поэтому токен принимаем query-параметром.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.db import SessionLocal
from app.deps import decode_token
from app.models import Courier, Order
from app.services.statuses import ACTIVE_FOR_COURIER, OrderStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/orders", tags=["tracking"])

POLL_INTERVAL_S = 2.0
HEARTBEAT_EVERY_S = 15.0
#: страховка от вечных соединений: через час клиент переподключится сам
MAX_STREAM_S = 3600.0

TERMINAL_STATUSES = {OrderStatus.delivered, OrderStatus.cancelled, OrderStatus.refunded}


def _sse(event: str, data: dict) -> str:
    """Собрать кадр SSE."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _snapshot(order_id: int, user_id: int) -> tuple[str, dict | None] | None:
    """Текущее состояние заказа: статус и позиция курьера.

    Отдельная короткая сессия на каждый опрос — держать соединение открытым
    весь стрим нельзя, пул кончится на первой сотне клиентов.
    """
    session = SessionLocal()
    try:
        order = session.get(Order, order_id)
        if order is None or order.user_id != user_id:
            return None
        position: dict | None = None
        if order.courier_id and OrderStatus(order.status) in ACTIVE_FOR_COURIER:
            courier = session.get(Courier, order.courier_id)
            if courier is not None and courier.lat is not None:
                position = {"lat": courier.lat, "lon": courier.lon}
        return OrderStatus(order.status).value, position
    finally:
        session.close()


async def _event_stream(order_id: int, user_id: int) -> AsyncIterator[str]:
    """Генератор кадров для одного подключения."""
    last_status: str | None = None
    last_position: dict | None = None
    since_heartbeat = 0.0
    elapsed = 0.0

    while elapsed < MAX_STREAM_S:
        snapshot = await asyncio.to_thread(_snapshot, order_id, user_id)
        if snapshot is None:
            yield _sse("error", {"detail": "заказ недоступен"})
            return

        current_status, position = snapshot
        if current_status != last_status:
            last_status = current_status
            since_heartbeat = 0.0
            yield _sse("status", {"order_id": order_id, "status": current_status})

        if position is not None and position != last_position:
            last_position = position
            since_heartbeat = 0.0
            yield _sse("courier_position", {"order_id": order_id, **position})

        if OrderStatus(current_status) in TERMINAL_STATUSES:
            logger.info("sse.closed", extra={"order_id": order_id, "status": current_status})
            return

        if since_heartbeat >= HEARTBEAT_EVERY_S:
            since_heartbeat = 0.0
            yield _sse("heartbeat", {})

        await asyncio.sleep(POLL_INTERVAL_S)
        since_heartbeat += POLL_INTERVAL_S
        elapsed += POLL_INTERVAL_S


@router.get("/{order_id}/stream")
async def stream_order(order_id: int, token: str = Query(min_length=10)) -> StreamingResponse:
    """SSE-поток статуса заказа."""
    payload = decode_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "в токене нет sub")

    logger.info("sse.open", extra={"order_id": order_id, "user_id": user_id})
    return StreamingResponse(
        _event_stream(order_id, int(user_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # отключаем буферизацию nginx, иначе события копятся пачками
            "X-Accel-Buffering": "no",
        },
    )
