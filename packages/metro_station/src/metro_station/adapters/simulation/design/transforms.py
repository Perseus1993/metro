from __future__ import annotations

from dataclasses import dataclass, replace

from .schema import DesignElement, DesignPort, ElementGeometry, QueueSpec


@dataclass(frozen=True)
class GeometryTransform:
    """An editor transform expressed in station metres.

    Ports scale with their owner. Attached queue geometry keeps its own dimensions and follows
    the owner's translation, which preserves queue capacity and service semantics while dragging.
    """

    old_x_m: float
    old_y_m: float
    old_width_m: float
    old_height_m: float
    new_x_m: float
    new_y_m: float
    new_width_m: float
    new_height_m: float

    @property
    def dx_m(self) -> float:
        return self.new_x_m - self.old_x_m

    @property
    def dy_m(self) -> float:
        return self.new_y_m - self.old_y_m

    @classmethod
    def between(
        cls,
        old_geometry: ElementGeometry,
        new_geometry: ElementGeometry,
    ) -> GeometryTransform:
        old_x, old_y, old_max_x, old_max_y = old_geometry.bounds()
        new_x, new_y, new_max_x, new_max_y = new_geometry.bounds()
        return cls(
            old_x_m=old_x,
            old_y_m=old_y,
            old_width_m=max(old_max_x - old_x, old_geometry.width_m, 1e-9),
            old_height_m=max(old_max_y - old_y, old_geometry.height_m, 1e-9),
            new_x_m=new_x,
            new_y_m=new_y,
            new_width_m=max(new_max_x - new_x, new_geometry.width_m, 1e-9),
            new_height_m=max(new_max_y - new_y, new_geometry.height_m, 1e-9),
        )

    def point(self, point_m: tuple[float, float]) -> tuple[float, float]:
        x_ratio = (point_m[0] - self.old_x_m) / self.old_width_m
        y_ratio = (point_m[1] - self.old_y_m) / self.old_height_m
        return (
            self.new_x_m + x_ratio * self.new_width_m,
            self.new_y_m + y_ratio * self.new_height_m,
        )


def transform_geometry(
    geometry: ElementGeometry,
    *,
    x_m: float,
    y_m: float,
    width_m: float | None = None,
    height_m: float | None = None,
) -> ElementGeometry:
    """Translate and, when requested, scale geometry around its bounding box."""

    if width_m is None and height_m is None:
        return geometry.moved_to(x_m, y_m)

    old_x, old_y, old_max_x, old_max_y = geometry.bounds()
    old_width = max(old_max_x - old_x, geometry.width_m, 1e-9)
    old_height = max(old_max_y - old_y, geometry.height_m, 1e-9)
    new_width = old_width if width_m is None else max(float(width_m), 1e-9)
    new_height = old_height if height_m is None else max(float(height_m), 1e-9)

    if geometry.shape in {"polygon", "polyline"} and geometry.points_m:
        points = tuple(
            (
                x_m + ((point_x - old_x) / old_width) * new_width,
                y_m + ((point_y - old_y) / old_height) * new_height,
            )
            for point_x, point_y in geometry.points_m
        )
        return ElementGeometry(
            shape=geometry.shape,
            x_m=x_m,
            y_m=y_m,
            width_m=new_width,
            height_m=new_height,
            rotation_deg=geometry.rotation_deg,
            points_m=points,
        )

    return ElementGeometry(
        shape=geometry.shape,
        x_m=x_m,
        y_m=y_m,
        width_m=new_width,
        height_m=new_height,
        rotation_deg=geometry.rotation_deg,
        points_m=geometry.points_m,
    )


def transform_element(
    element: DesignElement,
    *,
    x_m: float,
    y_m: float,
    width_m: float | None = None,
    height_m: float | None = None,
) -> tuple[DesignElement, GeometryTransform]:
    geometry = transform_geometry(
        element.geometry,
        x_m=x_m,
        y_m=y_m,
        width_m=width_m if element.resizable else None,
        height_m=height_m if element.resizable else None,
    )
    transform = GeometryTransform.between(element.geometry, geometry)
    ports = transform_ports(element.ports, transform)
    return replace(element, geometry=geometry, ports=ports), transform


def transform_ports(
    ports: tuple[DesignPort, ...],
    transform: GeometryTransform,
) -> tuple[DesignPort, ...]:
    return tuple(
        replace(port, position_m=transform.point(port.position_m))
        if port.position_m is not None
        else port
        for port in ports
    )


def translate_queue(queue: QueueSpec, dx_m: float, dy_m: float) -> QueueSpec:
    if abs(dx_m) <= 1e-12 and abs(dy_m) <= 1e-12:
        return queue
    old_x, old_y, _, _ = queue.geometry.bounds()
    return replace(
        queue,
        geometry=queue.geometry.moved_to(old_x + dx_m, old_y + dy_m),
        service_point_m=(
            queue.service_point_m[0] + dx_m,
            queue.service_point_m[1] + dy_m,
        ),
    )
