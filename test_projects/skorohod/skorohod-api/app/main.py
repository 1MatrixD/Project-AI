"""Точка входа: сборка FastAPI-приложения.

    uvicorn app.main:app --reload --port 8020
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.routers import admin, checkout, couriers, orders, payments, tracking
from app.services.pricing import DeliveryUnavailable
from app.services.statuses import InvalidTransition
from app.workers import assign_loop, stale_orders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Поднимаем фоновые воркеры вместе с приложением и глушим при остановке."""
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(assign_loop.run_forever(stop), name="assign_loop"),
        asyncio.create_task(stale_orders.run_forever(stop), name="stale_orders"),
    ]
    logger.info("app.start", extra={"version": __version__})
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("app.stop")


app = FastAPI(
    title="Скороход API",
    version=__version__,
    description="Доставка еды курьерами: заказы, зоны, промокоды, смены, платежи.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)
app.include_router(tracking.router)
app.include_router(checkout.router)
app.include_router(couriers.router)
app.include_router(admin.router)
app.include_router(payments.router)


@app.exception_handler(InvalidTransition)
async def invalid_transition_handler(request: Request, exc: InvalidTransition) -> JSONResponse:
    """Недопустимый переход статуса — это конфликт состояния, не 500."""
    logger.info("http.invalid_transition", extra={"path": request.url.path})
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DeliveryUnavailable)
async def delivery_unavailable_handler(request: Request, exc: DeliveryUnavailable) -> JSONResponse:
    """Адрес вне радиуса доставки."""
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "distance_m": exc.distance_m},
    )


@app.get("/health", tags=["service"])
def health() -> dict[str, str]:
    """Проверка живости для балансировщика."""
    return {"status": "ok", "version": __version__}


@app.get("/api/v2/meta", tags=["service"])
def meta() -> dict[str, object]:
    """Константы, которые фронт показывает в корзине до расчёта заказа."""
    return {
        "base_delivery_kop": settings.base_delivery_kop,
        "free_delivery_from_kop": settings.free_delivery_from_kop,
        "max_delivery_radius_m": settings.max_delivery_radius_m,
        "surge_enabled": settings.surge_enabled,
        "currency": "RUB",
    }
