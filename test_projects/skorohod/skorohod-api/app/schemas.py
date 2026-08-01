"""Pydantic-схемы запросов и ответов.

Правило: наружу отдаём только копейки (`*_kop`). Единственное исключение —
legacy-ответ `/api/v1/checkout`, где старая мобилка ждёт рубли строкой.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.statuses import OrderStatus

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class OrderItemIn(BaseModel):
    menu_item_id: int
    qty: int = Field(ge=1, le=50)

class OrderCreate(BaseModel):
    restaurant_id: int
    address_id: int
    items: list[OrderItemIn] = Field(min_length=1)
    promo_code: str | None = Field(default=None, max_length=40)
    comment: str = Field(default="", max_length=500)

class OrderItemOut(ORMModel):
    menu_item_id: int
    name: str
    price_kop: int
    qty: int

class OrderRead(ORMModel):
    id: int
    status: OrderStatus
    restaurant_id: int
    address_id: int
    courier_id: int | None = None
    subtotal_kop: int
    delivery_kop: int
    discount_kop: int
    total_kop: int
    promo_code: str | None = None
    comment: str = ""
    created_at: datetime
    delivered_at: datetime | None = None
    items: list[OrderItemOut] = []

class OrderListItem(ORMModel):
    id: int
    status: OrderStatus
    restaurant_id: int
    total_kop: int
    created_at: datetime

class CancelRequest(BaseModel):
    reason: str = Field(default="user_cancelled", max_length=120)

class CheckoutItemV1(BaseModel):
    id: int
    count: int = Field(ge=1, le=50)

class CheckoutRequestV1(BaseModel):
    """Тело старого чекаута. Имена полей менять нельзя — мобилка < 3.0."""

    restaurant: int
    address: int
    items: list[CheckoutItemV1] = Field(min_length=1)
    promo: str | None = None
    comment: str = ""

class CheckoutResponseV1(BaseModel):
    """Старый формат ответа: рубли строкой, `state` вместо `status`."""

    id: int
    state: str
    amount: str
    delivery_price: str
    promo_discount: str
    eta_minutes: int

class ShiftStart(BaseModel):
    zone_id: int

class ShiftRead(ORMModel):
    id: int
    courier_id: int
    zone_id: int
    started_at: datetime
    ended_at: datetime | None = None
    local_date: date

class PositionIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

class CourierOrder(ORMModel):
    id: int
    status: OrderStatus
    restaurant_id: int
    lat: float
    lon: float
    total_kop: int
    comment: str = ""

class PromoIn(BaseModel):
    code: str = Field(max_length=40)
    kind: Literal["percent", "fixed"] = "percent"
    value: int = Field(gt=0)
    min_total_kop: int = Field(default=0, ge=0)
    max_discount_kop: int | None = None
    per_user_limit: int | None = None
    total_limit: int | None = None
    active_from: datetime | None = None
    active_until: datetime | None = None
    is_active: bool = True

class PromoRead(PromoIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    used_total: int = 0

class ZoneIn(BaseModel):
    name: str = Field(max_length=120)
    #: вершины полигона [[lat, lon], ...], минимум три
    polygon: list[list[float]] = Field(min_length=3)
    is_active: bool = True

class ZoneRead(ORMModel):
    id: int
    name: str
    polygon: list[Any]
    bbox: list[Any]
    is_active: bool

class ZonePreviewIn(BaseModel):
    polygon: list[list[float]] = Field(min_length=3)
    points: list[list[float]] = Field(min_length=1)

class ZonePreviewOut(BaseModel):
    bbox: list[float]
    inside: list[bool]

class CourierReportRow(BaseModel):
    courier_id: int
    name: str
    orders: int
    delivered: int
    revenue_kop: int
    shift_minutes: int

class WebhookObject(BaseModel):
    payment_id: str
    order_id: int
    amount_kop: int

class WebhookIn(BaseModel):
    event_id: str
    type: str
    object: WebhookObject
