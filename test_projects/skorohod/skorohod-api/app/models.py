"""ORM-модели «Скорохода».

Соглашения: деньги — `int` в копейках (`*_kop`), время — `timestamptz` в UTC,
географию храним двумя колонками `lat`/`lon` (PostGIS в проект не тащим).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (JSON, Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.services.statuses import OrderStatus

status_enum = SAEnum(OrderStatus, name="order_status", native_enum=False,
                     values_callable=lambda enum: [item.value for item in enum])
ts = DateTime(timezone=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(ts, server_default=func.now())

class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    cook_minutes: Mapped[int] = mapped_column(Integer, default=20)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    price_kop: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    street: Mapped[str] = mapped_column(String(160))
    house: Mapped[str] = mapped_column(String(20))
    flat: Mapped[str] = mapped_column(String(20), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status_courier", "status", "courier_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("addresses.id"))
    courier_id: Mapped[int | None] = mapped_column(ForeignKey("couriers.id"), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(status_enum, default=OrderStatus.created, index=True)
    subtotal_kop: Mapped[int] = mapped_column(Integer, default=0)
    delivery_kop: Mapped[int] = mapped_column(Integer, default=0)
    discount_kop: Mapped[int] = mapped_column(Integer, default=0)
    total_kop: Mapped[int] = mapped_column(Integer, default=0)
    promo_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    #: координаты доставки, скопированные на момент оформления
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(ts, server_default=func.now(), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(ts, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order",
                                                    cascade="all, delete-orphan")
    courier: Mapped["Courier | None"] = relationship()
    restaurant: Mapped[Restaurant] = relationship()

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    #: название и цену копируем, чтобы историю не ломало редактирование меню
    name: Mapped[str] = mapped_column(String(160))
    price_kop: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    order: Mapped[Order] = relationship(back_populates="items")

class Courier(Base):
    __tablename__ = "couriers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_updated_at: Mapped[datetime | None] = mapped_column(ts, nullable=True)

class Shift(Base):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(ts)
    ended_at: Mapped[datetime | None] = mapped_column(ts, nullable=True)
    #: московский день, к которому отнесена смена
    local_date: Mapped[date] = mapped_column(Date, index=True)

class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    #: вершины полигона [[lat, lon], ...], первая и последняя не совпадают
    polygon: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: [min_lat, min_lon, max_lat, max_lon], пересчитывается при сохранении зоны
    bbox: Mapped[list[Any]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Promo(Base):
    __tablename__ = "promos"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    #: percent | fixed
    kind: Mapped[str] = mapped_column(String(10), default="percent")
    #: для percent — проценты, для fixed — копейки
    value: Mapped[int] = mapped_column(Integer)
    min_total_kop: Mapped[int] = mapped_column(Integer, default=0)
    max_discount_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_from: Mapped[datetime | None] = mapped_column(ts, nullable=True)
    active_until: Mapped[datetime | None] = mapped_column(ts, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class PromoUsage(Base):
    __tablename__ = "promo_usages"
    __table_args__ = (UniqueConstraint("order_id", name="uq_promo_usage_order"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    discount_kop: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(ts, server_default=func.now())

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    amount_kop: Mapped[int] = mapped_column(Integer)
    #: hold | captured | refunded | failed
    status: Mapped[str] = mapped_column(String(20), default="hold")
    captured_at: Mapped[datetime | None] = mapped_column(ts, nullable=True)
    created_at: Mapped[datetime] = mapped_column(ts, server_default=func.now())

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(40))
    received_at: Mapped[datetime] = mapped_column(ts, server_default=func.now())

class StatusHistory(Base):
    __tablename__ = "status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[OrderStatus] = mapped_column(status_enum)
    to_status: Mapped[OrderStatus] = mapped_column(status_enum)
    #: user:12 / courier:4 / worker:assign / webhook
    actor: Mapped[str] = mapped_column(String(40), default="system")
    created_at: Mapped[datetime] = mapped_column(ts, server_default=func.now())
