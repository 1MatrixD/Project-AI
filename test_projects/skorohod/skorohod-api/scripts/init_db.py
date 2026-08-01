"""Создание таблиц и демо-данные для локального запуска.

    python -m scripts.init_db

Идемпотентно: если пользователи уже есть, наполнение пропускается.
Миграций у сервиса пока нет — схема раскатывается из моделей.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import (Address, Courier, MenuItem, Order, OrderItem, Promo,
                        Restaurant, Shift, User, Zone)
from app.services.statuses import OrderStatus
from app.utils.timeutil import local_day, now_utc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("init_db")


def seed(session) -> None:
    """Наполнить базу минимальным, но связным набором данных."""
    now = now_utc()

    client = User(phone="+79001112233", name="Аня Клиентова")
    admin = User(phone="+79005550000", name="Оператор", is_admin=True)
    courier_users = [
        User(phone="+79007770001", name="Пётр Гонцов"),
        User(phone="+79007770002", name="Мурат Быстров"),
        User(phone="+79007770003", name="Лена Скорая"),
    ]
    session.add_all([client, admin, *courier_users])
    session.flush()

    lavka = Restaurant(name="Лавка Хинкали", lat=55.7420, lon=37.6350, cook_minutes=25)
    pizza = Restaurant(name="Пицца у Депо", lat=55.7550, lon=37.6180, cook_minutes=18)
    session.add_all([lavka, pizza])
    session.flush()

    menu = [
        MenuItem(restaurant_id=lavka.id, name="Хинкали с бараниной, 5 шт", price_kop=59000),
        MenuItem(restaurant_id=lavka.id, name="Хачапури по-аджарски", price_kop=64000),
        MenuItem(restaurant_id=lavka.id, name="Лимонад тархун", price_kop=19000),
        MenuItem(restaurant_id=pizza.id, name="Пепперони 30 см", price_kop=78000),
        MenuItem(restaurant_id=pizza.id, name="Четыре сыра 30 см", price_kop=86000),
        MenuItem(restaurant_id=pizza.id, name="Салат цезарь", price_kop=42000),
    ]
    session.add_all(menu)
    session.flush()

    home = Address(user_id=client.id, street="Пятницкая", house="27", flat="14",
                   lat=55.7345, lon=37.6285, comment="код домофона 14В")
    office = Address(user_id=client.id, street="Автозаводская", house="18",
                     lat=55.7065, lon=37.6570)
    session.add_all([home, office])
    session.flush()

    # Полигон «Центра» вытянут по диагонали, поэтому его bbox накрывает
    # заметный кусок соседнего Замоскворечья.
    centre = Zone(
        name="Центр",
        polygon=[[55.7580, 37.6000], [55.7620, 37.6520], [55.7220, 37.6620], [55.7180, 37.6100]],
        bbox=[55.7180, 37.6000, 55.7620, 37.6620],
    )
    zamoskvorechye = Zone(
        name="Замоскворечье",
        polygon=[[55.7360, 37.6240], [55.7405, 37.6430], [55.7255, 37.6480], [55.7210, 37.6300]],
        bbox=[55.7210, 37.6240, 55.7405, 37.6480],
    )
    south = Zone(
        name="Автозаводская",
        polygon=[[55.7120, 37.6480], [55.7150, 37.6700], [55.6980, 37.6720], [55.6950, 37.6500]],
        bbox=[55.6950, 37.6480, 55.7150, 37.6720],
    )
    session.add_all([centre, zamoskvorechye, south])
    session.flush()

    couriers = [
        Courier(user_id=courier_users[0].id, name="Пётр Гонцов", phone="+79007770001",
                lat=55.7500, lon=37.6200, position_updated_at=now),
        Courier(user_id=courier_users[1].id, name="Мурат Быстров", phone="+79007770002",
                lat=55.7300, lon=37.6350, position_updated_at=now),
        Courier(user_id=courier_users[2].id, name="Лена Скорая", phone="+79007770003",
                lat=55.7050, lon=37.6600, position_updated_at=now),
    ]
    session.add_all(couriers)
    session.flush()

    today = local_day(now)
    session.add_all([
        Shift(courier_id=couriers[0].id, zone_id=centre.id, started_at=now - timedelta(hours=3),
              local_date=today),
        Shift(courier_id=couriers[1].id, zone_id=zamoskvorechye.id,
              started_at=now - timedelta(hours=2), local_date=today),
        Shift(courier_id=couriers[2].id, zone_id=south.id, started_at=now - timedelta(hours=5),
              local_date=today),
    ])

    session.add_all([
        Promo(code="ЛЕТО300", kind="fixed", value=30000, min_total_kop=150000,
              per_user_limit=None, total_limit=500),
        Promo(code="ПЕРВЫЙ", kind="percent", value=15, min_total_kop=100000,
              max_discount_kop=50000, per_user_limit=1),
        Promo(code="НОЧЬ10", kind="percent", value=10, min_total_kop=0, per_user_limit=None),
    ])

    # Пара заказов, чтобы список и отчёт не были пустыми.
    # Ночной заказ намеренно оформлен в 01:20 МСК — на нём удобно смотреть суточный отчёт.
    night = now.replace(hour=22, minute=20, second=0, microsecond=0) - timedelta(days=1)
    orders = [
        Order(user_id=client.id, restaurant_id=lavka.id, address_id=home.id,
              courier_id=couriers[1].id, status=OrderStatus.delivered,
              subtotal_kop=123000, delivery_kop=14900, discount_kop=0, total_kop=137900,
              lat=home.lat, lon=home.lon, created_at=night,
              delivered_at=night + timedelta(minutes=48)),
        Order(user_id=client.id, restaurant_id=pizza.id, address_id=office.id,
              courier_id=couriers[2].id, status=OrderStatus.cancelled,
              subtotal_kop=78000, delivery_kop=14900, discount_kop=0, total_kop=92900,
              lat=office.lat, lon=office.lon, created_at=now - timedelta(hours=4)),
        Order(user_id=client.id, restaurant_id=lavka.id, address_id=home.id,
              status=OrderStatus.paid, subtotal_kop=142000, delivery_kop=0,
              discount_kop=30000, total_kop=112000, promo_code="ЛЕТО300",
              lat=home.lat, lon=home.lon, created_at=now - timedelta(minutes=12)),
    ]
    session.add_all(orders)
    session.flush()

    session.add_all([
        OrderItem(order_id=orders[0].id, menu_item_id=menu[0].id, name=menu[0].name,
                  price_kop=menu[0].price_kop, qty=2),
        OrderItem(order_id=orders[1].id, menu_item_id=menu[3].id, name=menu[3].name,
                  price_kop=menu[3].price_kop, qty=1),
        OrderItem(order_id=orders[2].id, menu_item_id=menu[1].id, name=menu[1].name,
                  price_kop=menu[1].price_kop, qty=1),
        OrderItem(order_id=orders[2].id, menu_item_id=menu[2].id, name=menu[2].name,
                  price_kop=menu[2].price_kop, qty=4),
    ])
    session.commit()
    logger.info("демо-данные загружены")


def main() -> None:
    Base.metadata.create_all(engine)
    logger.info("схема создана")

    with SessionLocal() as session:
        if session.scalar(select(User).limit(1)) is not None:
            logger.info("данные уже есть, наполнение пропущено")
            return
        seed(session)


if __name__ == "__main__":
    main()
