from __future__ import annotations

from random import Random
from typing import Iterable

from shapely import intersects_xy
from shapely.geometry import LineString, Point as ShapelyPoint, box
from shapely.ops import nearest_points, unary_union
from shapely.validation import make_valid

from ..design.geometry import element_shape
from ..design.geometry import level_walkable_geometry as level_walkable_geometry
from ..design.schema import DesignElement, ElementGeometry, StationDesignDocument


Point = tuple[float, float]


def element_representative_point(geometry: ElementGeometry) -> Point:
    if geometry.shape == "polyline" and geometry.points_m:
        points = geometry.points_m
        if len(points) == 1:
            return points[0]
        half_length = LineString(points).length / 2.0
        point = LineString(points).interpolate(half_length)
        return float(point.x), float(point.y)
    shape = element_shape(geometry)
    point = shape.representative_point()
    return float(point.x), float(point.y)


def document_walkable_geometry(document: StationDesignDocument):
    parts = [
        element_shape(element.geometry)
        for element in document.elements
        if element.kind == "walkable_area" or element.role == "floor"
    ]
    if not parts:
        return box(
            0.0, 0.0, document.constraints.canvas_width_m, document.constraints.canvas_height_m
        )
    walkable = make_valid(unary_union(parts))
    obstacles = [
        element_shape(element.geometry)
        for element in document.elements
        if (element.kind == "obstacle" or element.role == "obstacle")
        and bool(element.metadata.get("blocking", True))
    ]
    if obstacles:
        walkable = walkable.difference(unary_union(obstacles))
    return make_valid(walkable)


def element_walkable_domain(
    element: DesignElement,
    walkable_geometry,
):
    shape = element_shape(element.geometry)
    if element.kind == "walkable_area" or element.role == "floor":
        domain = walkable_geometry.intersection(shape)
        return make_valid(domain) if not domain.is_empty else walkable_geometry
    return walkable_geometry


def safe_core(geometry, clearance: float):
    core = geometry.buffer(-max(0.0, clearance))
    if core.is_empty:
        return geometry
    return make_valid(core)


def project_to_safe_point(
    geometry,
    point: Point,
    *,
    clearance: float = 0.18,
    require_inside: bool = False,
) -> Point:
    source = ShapelyPoint(point)
    if require_inside and not geometry.covers(source):
        raise RuntimeError(f"Point {point!r} is outside the walkable geometry.")

    core = safe_core(geometry, clearance)
    if core.covers(source):
        return point
    _source, projected = nearest_points(source, core)
    return float(projected.x), float(projected.y)


def representative_safe_point(
    geometry,
    *,
    clearance: float = 0.18,
) -> Point:
    point = geometry.representative_point()
    return project_to_safe_point(
        geometry,
        (float(point.x), float(point.y)),
        clearance=clearance,
        require_inside=False,
    )


def sample_safe_point(
    geometry,
    rng: Random,
    *,
    clearance: float = 0.18,
    attempts: int = 120,
) -> Point:
    core = safe_core(geometry, clearance)
    min_x, min_y, max_x, max_y = core.bounds
    for _ in range(max(1, attempts)):
        candidate = (rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
        if core.covers(ShapelyPoint(candidate)):
            return candidate
    return representative_safe_point(core, clearance=0.0)


def grid_safe_points(
    geometry,
    *,
    spacing: float = 0.85,
    clearance: float = 0.18,
) -> tuple[Point, ...]:
    core = safe_core(geometry, clearance)
    if core.is_empty:
        return ()
    min_x, min_y, max_x, max_y = core.bounds
    candidates: list[Point] = []
    y = min_y + spacing / 2.0
    while y <= max_y - spacing / 2.0:
        x = min_x + spacing / 2.0
        while x <= max_x - spacing / 2.0:
            # Capacity certificates compare this lattice against the exact
            # requested spacing.  Six decimals keep the rounding error below
            # the compiler's numerical tolerance for sub-metre body grids.
            candidates.append((round(x, 6), round(y, 6)))
            x += spacing
        y += spacing
    if not candidates:
        return ()
    # Batch the lattice classification in GEOS instead of constructing and
    # classifying thousands of Python Point objects one by one. Candidates sit
    # half a spacing inside the grid bounds; ``intersects_xy`` also preserves
    # the previous ``covers`` behaviour for any point exactly on a hole edge.
    mask = intersects_xy(
        core,
        [point[0] for point in candidates],
        [point[1] for point in candidates],
    )
    return tuple(
        point for point, included in zip(candidates, mask, strict=True) if included
    )


def dedupe_points(points: Iterable[Point], *, precision: int = 3) -> tuple[Point, ...]:
    seen: set[tuple[float, float]] = set()
    deduped: list[Point] = []
    for point in points:
        key = (round(point[0], precision), round(point[1], precision))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return tuple(deduped)
