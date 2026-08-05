from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

from .schema import ElementGeometry, StationDesignDocument


def element_shape(geometry: ElementGeometry, *, line_width: float = 0.4):
    """Build the editable geometry represented by a design element."""
    if geometry.shape == "rect":
        shape = box(
            geometry.x_m,
            geometry.y_m,
            geometry.x_m + geometry.width_m,
            geometry.y_m + geometry.height_m,
        )
        if abs(float(geometry.rotation_deg)) > 1e-9:
            shape = rotate(
                shape,
                float(geometry.rotation_deg),
                origin=geometry.center(),
                use_radians=False,
            )
        return shape
    if geometry.shape == "polygon" and geometry.points_m:
        return Polygon(geometry.points_m)
    if geometry.shape == "polyline" and geometry.points_m:
        return LineString(geometry.points_m).buffer(line_width / 2.0, cap_style="round")
    if geometry.shape == "point":
        return Point((geometry.x_m, geometry.y_m)).buffer(line_width / 2.0)
    return Point(geometry.center()).buffer(line_width / 2.0)


def level_walkable_geometry(
    document: StationDesignDocument,
    level_id: str,
    walkable_geometry=None,
):
    """Return one level's walking domain without cross-floor leakage."""

    level_parts = [
        element_shape(element.geometry)
        for element in document.elements
        if element.level_id == level_id
        and (element.kind == "walkable_area" or element.role == "floor")
    ]
    if level_parts:
        base = make_valid(unary_union(level_parts))
    else:
        level = document.level_by_id().get(level_id)
        if level is not None and level.footprint:
            base = make_valid(Polygon(level.footprint))
        elif walkable_geometry is not None:
            base = make_valid(walkable_geometry)
        else:
            base = box(
                0.0,
                0.0,
                document.constraints.canvas_width_m,
                document.constraints.canvas_height_m,
            )

    obstacles = [
        element_shape(element.geometry)
        for element in document.elements
        if element.level_id == level_id
        and (element.kind == "obstacle" or element.role == "obstacle")
        and bool(element.metadata.get("blocking", True))
    ]
    if obstacles:
        base = base.difference(unary_union(obstacles))
    return make_valid(base)
