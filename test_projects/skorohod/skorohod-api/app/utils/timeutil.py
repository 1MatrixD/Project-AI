"""Работа со временем.

Правило проекта: в базе всё в UTC (`timestamptz`), пользователю и в отчётах
показываем московское время. Операционные сутки курьера — тоже московские.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

#: Москва без перехода на летнее время с 2014 года, поэтому фиксированный офсет
#: честнее, чем тянуть zoneinfo ради одной зоны.
MSK = timezone(timedelta(hours=3), name="MSK")

UTC = timezone.utc

#: Ночная доставка: с 23:00 до 06:00 по Москве.
NIGHT_FROM = time(23, 0)
NIGHT_TO = time(6, 0)


def now_utc() -> datetime:
    """Текущий момент в UTC, всегда aware."""
    return datetime.now(tz=UTC)


def ensure_aware(dt: datetime) -> datetime:
    """Наивную дату считаем UTC — так их отдаёт psycopg для колонок без tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def to_local(dt: datetime) -> datetime:
    """Перевести момент в московское время."""
    return ensure_aware(dt).astimezone(MSK)


def local_day(dt: datetime) -> date:
    """Календарный день по Москве, к которому относится момент.

    Используется для смен и любых «за какой день» вопросов: заказ, созданный
    в 01:30 МСК, относится к новому дню, хотя в UTC это ещё вчера.
    """
    return to_local(dt).date()


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Границы московских суток `day` в UTC: [начало, начало следующего дня)."""
    start_local = datetime.combine(day, time(0, 0), tzinfo=MSK)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def is_night(dt: datetime) -> bool:
    """Попадает ли момент в ночное окно по Москве."""
    local_time = to_local(dt).time()
    return local_time >= NIGHT_FROM or local_time < NIGHT_TO


def minutes_between(start: datetime, end: datetime) -> int:
    """Целых минут между двумя моментами (не меньше нуля)."""
    delta = ensure_aware(end) - ensure_aware(start)
    return max(0, int(delta.total_seconds() // 60))


def fmt_local(dt: datetime) -> str:
    """Человекочитаемое время для СМС и пушей: `05.08 в 19:40`."""
    return to_local(dt).strftime("%d.%m в %H:%M")
