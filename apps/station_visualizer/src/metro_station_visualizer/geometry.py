from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

try:  # Support both package execution and direct script execution.
    from .config import H, PX_PER_METER, W
    from .layout import STATION_LAYOUT
except ImportError:  # pragma: no cover
    from config import H, PX_PER_METER, W
    from layout import STATION_LAYOUT


def px(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] * W, point[1] * H


def meters(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] * W / PX_PER_METER, point[1] * H / PX_PER_METER


def canvas(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] * PX_PER_METER, point[1] * PX_PER_METER


def normalized_ring_to_meters(points: tuple[tuple[float, float], ...]) -> list[tuple[float, float]]:
    return [meters((float(x), float(y))) for x, y in points]


def load_station_geometry() -> Polygon:
    walkable_parts = [
        Polygon(normalized_ring_to_meters(region.points))
        for region in STATION_LAYOUT.walkable_regions
    ]
    for channel in STATION_LAYOUT.connector_channels:
        line = LineString(normalized_ring_to_meters(channel.line))
        width_m = float(channel.width_px) / PX_PER_METER
        walkable_parts.append(line.buffer(width_m / 2.0, cap_style="round", join_style="round"))

    geometry = unary_union(walkable_parts)
    obstacles = [
        Polygon(normalized_ring_to_meters(obstacle.points))
        for obstacle in STATION_LAYOUT.obstacles
        if obstacle.blocking
    ]
    if obstacles:
        geometry = geometry.difference(unary_union(obstacles))
    geometry = make_valid(geometry)
    if geometry.geom_type == "GeometryCollection":
        polygons = [
            geom for geom in geometry.geoms if geom.geom_type in {"Polygon", "MultiPolygon"}
        ]
        geometry = unary_union(polygons)
    return geometry
