"""Деньги.

Единственное место в проекте, где допустимо округление. Внутри системы всё
хранится и считается в копейках (`int`), рубли появляются только на границе:
в legacy-ответах и в текстах уведомлений.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

KOP_IN_RUB = 100


def rub_to_kop(rub: Decimal | float | int | str) -> int:
    """Рубли -> копейки. Половинки округляем вверх, как в кассе."""
    value = Decimal(str(rub)) * KOP_IN_RUB
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def kop_to_rub(kop: int) -> Decimal:
    """Копейки -> рубли с двумя знаками. Для сериализации в legacy-ответы."""
    return (Decimal(kop) / KOP_IN_RUB).quantize(Decimal("0.01"))


def round_kop(value: Decimal | float | int) -> int:
    """Округлить промежуточный расчёт (проценты, коэффициенты) до копейки."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def percent_of(kop: int, percent: Decimal | float | int) -> int:
    """Процент от суммы в копейках."""
    return round_kop(Decimal(kop) * Decimal(str(percent)) / 100)


def fmt_rub(kop: int) -> str:
    """Строка для человека: `1 249 ₽` или `1 249,50 ₽`."""
    rub = kop_to_rub(kop)
    whole, _, frac = f"{rub:.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    if frac == "00":
        return f"{grouped} ₽"
    return f"{grouped},{frac} ₽"


def clamp_non_negative(kop: int) -> int:
    """Итог заказа не может уйти в минус — скидка не больше суммы."""
    return kop if kop > 0 else 0


def parse_rub(text: str) -> int:
    """Разобрать сумму, введённую руками в админке: `1 249,50` -> 124950."""
    cleaned = text.replace(" ", "").replace(" ", "").replace("₽", "").replace(",", ".")
    if not cleaned:
        raise ValueError("пустая сумма")
    return rub_to_kop(cleaned)


def distribute_kop(total_kop: int, weights: list[int]) -> list[int]:
    """Разложить сумму по позициям пропорционально весам, без потери копеек.

    Нужно для чеков: скидка на заказ должна разойтись по блюдам так, чтобы
    сумма частей в точности совпала с исходной.
    """
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)
    parts = [total_kop * weight // weight_sum for weight in weights]
    remainder = total_kop - sum(parts)
    index = 0
    while remainder > 0 and parts:
        parts[index % len(parts)] += 1
        remainder -= 1
        index += 1
    return parts
