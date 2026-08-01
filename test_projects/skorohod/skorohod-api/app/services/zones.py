"""Геометрия зон доставки.

Зона — полигон из вершин `[[lat, lon], ...]` плюс предрассчитанный bbox
`[min_lat, min_lon, max_lat, max_lon]`. Bbox — дешёвый префильтр: он всегда
шире полигона, поэтому «точка в bbox» — необходимое, но не достаточное
условие попадания в зону.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Zone

#: Точка — всегда (широта, долгота).
Point = tuple[float, float]
Polygon = list[list[float]]
BBox = list[float]

EARTH_RADIUS_M = 6_371_000.0


def bbox_of(polygon: Polygon) -> BBox:
    """Описывающий прямоугольник полигона.

    Вызывается при сохранении зоны в админке, результат кладётся в `zone.bbox`.
    """
    if not polygon:
        raise ValueError("полигон пустой")
    lats = [float(vertex[0]) for vertex in polygon]
    lons = [float(vertex[1]) for vertex in polygon]
    return [min(lats), min(lons), max(lats), max(lons)]


def bbox_contains(bbox: BBox, point: Point) -> bool:
    """Лежит ли точка внутри bbox (границы включительно)."""
    if not bbox or len(bbox) != 4:
        return False
    min_lat, min_lon, max_lat, max_lon = bbox
    lat, lon = point
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def point_in_polygon(polygon: Polygon, point: Point) -> bool:
    """Точная проверка вхождения точки в полигон (ray casting).

    Луч пускаем вдоль долготы; вершины, лежащие ровно на луче, считаем
    относящимися к верхнему ребру — так точка на общей границе двух зон
    попадёт ровно в одну.
    """
    if not polygon or len(polygon) < 3:
        return False
    lat, lon = point
    inside = False
    count = len(polygon)
    for index in range(count):
        lat_i, lon_i = float(polygon[index][0]), float(polygon[index][1])
        lat_j, lon_j = float(polygon[index - 1][0]), float(polygon[index - 1][1])
        crosses = (lat_i > lat) != (lat_j > lat)
        if not crosses:
            continue
        if lat_j == lat_i:
            continue
        lon_at_ray = (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
        if lon < lon_at_ray:
            inside = not inside
    return inside


def haversine_m(a: Point, b: Point) -> float:
    """Расстояние между двумя точками по большому кругу, метры."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def zone_for_point(session: Session, point: Point) -> Zone | None:
    """Найти активную зону, которой принадлежит точка.

    Зоны в городе не пересекаются, поэтому возвращаем первую подошедшую.
    """
    zones = session.scalars(select(Zone).where(Zone.is_active.is_(True))).all()
    for zone in zones:
        if bbox_contains(zone.bbox, point):
            return zone
    return None


def zones_bulk(session: Session) -> dict[int, Zone]:
    """Все активные зоны словарём по id — чтобы не дёргать базу в цикле."""
    zones = session.scalars(select(Zone).where(Zone.is_active.is_(True))).all()
    return {zone.id: zone for zone in zones}


def polygon_center(polygon: Polygon) -> Point:
    """Центроид по вершинам. Достаточно точно для превью в админке."""
    lats = [float(vertex[0]) for vertex in polygon]
    lons = [float(vertex[1]) for vertex in polygon]
    return sum(lats) / len(lats), sum(lons) / len(lons)
