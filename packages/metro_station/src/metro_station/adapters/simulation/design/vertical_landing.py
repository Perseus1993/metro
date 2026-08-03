from __future__ import annotations

from math import cos, hypot, radians, sin
from typing import Any

from shapely.geometry import Point as ShapelyPoint, Polygon
from shapely.ops import nearest_points, unary_union
from shapely.validation import make_valid

from .geometry import element_shape
from .helpers import vertical_direction
from .schema import DesignElement, StationDesignDocument


Point = tuple[float, float]


def design_level_walkable_geometry(
    document: StationDesignDocument,
    level_id: str,
):
    """Build the same level-specific walking domain used for landing projection."""

    all_parts = [
        element_shape(element.geometry)
        for element in document.elements
        if element.kind == "walkable_area" or element.role == "floor"
    ]
    if not all_parts:
        level = document.level_by_id()[level_id]
        return make_valid(Polygon(level.footprint))
    walkable = make_valid(unary_union(all_parts))
    obstacles = [
        element_shape(element.geometry)
        for element in document.elements
        if (element.kind == "obstacle" or element.role == "obstacle")
        and bool(element.metadata.get("blocking", True))
    ]
    if obstacles:
        walkable = make_valid(walkable.difference(unary_union(obstacles)))
    level_parts = [
        element_shape(element.geometry)
        for element in document.elements
        if element.level_id == level_id
        and (element.kind == "walkable_area" or element.role == "floor")
    ]
    if not level_parts:
        return walkable
    return make_valid(walkable.intersection(unary_union(level_parts)))


def vertical_facade_pairs(
    element: DesignElement,
    levels_by_id: dict[str, Any],
) -> tuple[tuple[str, str, str], ...]:
    """Return every directional service facade as (direction, entry, exit)."""

    ordered = _ordered_levels(element, levels_by_id)
    configured = vertical_direction(element)
    pairs: list[tuple[str, str, str]] = []
    for upper, lower in zip(ordered, ordered[1:], strict=False):
        if configured in {"down", "both"}:
            pairs.append(("down", upper, lower))
        if configured in {"up", "both"}:
            pairs.append(("up", lower, upper))
    return tuple(pairs)


def vertical_landing_position(
    element: DesignElement,
    level_id: str,
    levels_by_id: dict[str, Any] | None = None,
    *,
    walkable_geometry=None,
    clearance: float = 0.18,
) -> Point:
    """Derive one landing portal from connector geometry and level order.

    Design generation and graph compilation call this same primitive.  Optional
    projection makes the result a body-clear point in the entry floor domain.
    """

    ordered = _ordered_levels(element, levels_by_id)
    raw = _raw_landing_position(element, level_id, ordered, clearance=clearance)
    if walkable_geometry is None:
        return raw
    core = walkable_geometry.buffer(-max(0.0, clearance))
    if core.is_empty:
        core = walkable_geometry
    source = ShapelyPoint(raw)
    if core.covers(source):
        return raw
    _source, projected = nearest_points(source, core)
    return float(projected.x), float(projected.y)


def vertical_interior_direction(
    element: DesignElement,
    entry_level_id: str,
    exit_level_id: str,
    levels_by_id: dict[str, Any],
    *,
    entry_walkable_geometry=None,
    exit_walkable_geometry=None,
) -> Point:
    """Unit vector from a landing into the connector travel/cabin domain."""

    entry = vertical_landing_position(
        element,
        entry_level_id,
        levels_by_id,
        walkable_geometry=entry_walkable_geometry,
    )
    exit = vertical_landing_position(
        element,
        exit_level_id,
        levels_by_id,
        walkable_geometry=exit_walkable_geometry,
    )
    dx = exit[0] - entry[0]
    dy = exit[1] - entry[1]
    length = hypot(dx, dy)
    if length > 1e-9:
        return dx / length, dy / length

    # Stacked elevator landings can share one XY coordinate.  Its door portal
    # is on the local lower-y edge, so the cabin interior is local +y.
    angle = radians(float(element.geometry.rotation_deg))
    return -sin(angle), cos(angle)


def _ordered_levels(
    element: DesignElement,
    levels_by_id: dict[str, Any] | None,
) -> tuple[str, ...]:
    if levels_by_id is None:
        return tuple(element.connects_levels)
    return tuple(
        sorted(
            element.connects_levels,
            key=lambda level_id: levels_by_id[level_id].elevation_m,
            reverse=True,
        )
    )


def _raw_landing_position(
    element: DesignElement,
    level_id: str,
    ordered_levels: tuple[str, ...],
    *,
    clearance: float,
) -> Point:
    geometry = element.geometry
    if geometry.shape == "polyline" and geometry.points_m:
        level_index = ordered_levels.index(level_id)
        point_index = round(
            level_index * (len(geometry.points_m) - 1) / max(1, len(ordered_levels) - 1)
        )
        return geometry.points_m[point_index]

    center_x, center_y = geometry.center()
    if geometry.shape == "rect" and element.kind in {"stairs", "escalator"}:
        level_index = ordered_levels.index(level_id)
        ratio = level_index / max(1, len(ordered_levels) - 1)
        inset = max(0.0, clearance)
        if geometry.width_m >= geometry.height_m:
            usable = max(0.0, geometry.width_m - inset * 2.0)
            raw = geometry.x_m + inset + usable * ratio, center_y
        else:
            usable = max(0.0, geometry.height_m - inset * 2.0)
            raw = center_x, geometry.y_m + inset + usable * ratio
        return _rotate(raw, (center_x, center_y), geometry.rotation_deg)

    if geometry.shape == "rect" and element.kind == "elevator":
        raw = center_x, geometry.y_m
        return _rotate(raw, (center_x, center_y), geometry.rotation_deg)
    return center_x, center_y


def _rotate(point: Point, center: Point, rotation_deg: float) -> Point:
    angle = radians(float(rotation_deg))
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return (
        center[0] + dx * cos(angle) - dy * sin(angle),
        center[1] + dx * sin(angle) + dy * cos(angle),
    )
