from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box

from .schema import ElementGeometry


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
