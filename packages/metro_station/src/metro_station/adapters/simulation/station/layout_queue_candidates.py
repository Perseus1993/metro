from __future__ import annotations

from math import ceil, floor, hypot

from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint
from shapely.ops import nearest_points

from ..design.schema import MIN_COMPILED_QUEUE_SPACING_M, QueueSpec
from .geometry import dedupe_points, element_shape
from .layout_queue_path import (
    QUEUE_CLEARANCE_EPSILON_M,
    segment_distance,
)
from .layout_types import Point


_QUEUE_COORDINATE_DECIMALS = 6


def queue_slot_candidates(
    queue: QueueSpec,
    walkable_geometry,
    *,
    phase_u: float = 0.0,
    phase_v: float = 0.0,
) -> tuple[tuple[Point, ...], object]:
    shape = element_shape(queue.geometry)
    domain = shape
    if walkable_geometry is not None:
        clipped = shape.intersection(walkable_geometry)
        if clipped.is_empty:
            raise ValueError(
                f"queue {queue.id!r} has no overlap with the walkable domain"
            )
        if clipped.geom_type not in {"Polygon", "MultiPolygon"} or clipped.area <= 1e-9:
            raise ValueError(
                f"queue {queue.id!r} touches the walkable domain without usable area"
            )
        domain = clipped
    domain = service_connected_queue_domain(domain, queue.service_point_m)

    spacing = max(0.2, float(queue.spacing_m))
    body_clearance = min(0.18, spacing * 0.2)
    core = domain.buffer(-body_clearance)
    if (
        core.is_empty
        or core.geom_type not in {"Polygon", "MultiPolygon"}
        or core.area <= 1e-9
    ):
        raise ValueError(
            f"queue {queue.id!r} has no body-clear area at {body_clearance:.3f} m clearance"
        )
    axis_u, axis_v = _queue_lattice_axes(core, queue.service_point_m)
    origin = (
        queue.service_point_m[0]
        + axis_u[0] * phase_u * spacing
        + axis_v[0] * phase_v * spacing,
        queue.service_point_m[1]
        + axis_u[1] * phase_u * spacing
        + axis_v[1] * phase_v * spacing,
    )
    corners = tuple(core.minimum_rotated_rectangle.exterior.coords[:-1])
    u_values = [
        (point[0] - origin[0]) * axis_u[0] + (point[1] - origin[1]) * axis_u[1]
        for point in corners
    ]
    v_values = [
        (point[0] - origin[0]) * axis_v[0] + (point[1] - origin[1]) * axis_v[1]
        for point in corners
    ]
    candidates: list[Point] = []
    min_u = int(floor(min(u_values) / spacing)) - 1
    max_u = int(ceil(max(u_values) / spacing)) + 1
    min_v = int(floor(min(v_values) / spacing)) - 1
    max_v = int(ceil(max(v_values) / spacing)) + 1
    for v_index in range(min_v, max_v + 1):
        for u_index in range(min_u, max_u + 1):
            point = (
                round(
                    origin[0]
                    + axis_u[0] * u_index * spacing
                    + axis_v[0] * v_index * spacing,
                    _QUEUE_COORDINATE_DECIMALS,
                ),
                round(
                    origin[1]
                    + axis_u[1] * u_index * spacing
                    + axis_v[1] * v_index * spacing,
                    _QUEUE_COORDINATE_DECIMALS,
                ),
            )
            if core.covers(ShapelyPoint(point)):
                candidates.append(point)

    if not candidates:
        representative = core.representative_point()
        candidates = [(float(representative.x), float(representative.y))]

    return tuple(dedupe_points(candidates)), domain


def _queue_lattice_axes(domain, service_point: Point) -> tuple[Point, Point]:
    rectangle = domain.minimum_rotated_rectangle
    coordinates = tuple(rectangle.exterior.coords[:-1])
    if len(coordinates) < 2:
        return (1.0, 0.0), (0.0, 1.0)
    edges = [
        (
            coordinates[(index + 1) % len(coordinates)][0] - point[0],
            coordinates[(index + 1) % len(coordinates)][1] - point[1],
        )
        for index, point in enumerate(coordinates)
    ]
    centroid = domain.centroid
    tail = _normalize(
        (float(centroid.x) - service_point[0], float(centroid.y) - service_point[1])
    )
    axis_u = _normalize(
        max(
            edges,
            key=lambda edge: (
                round(
                    abs(
                        _normalize(edge)[0] * tail[0]
                        + _normalize(edge)[1] * tail[1]
                    ),
                    9,
                ),
                hypot(*edge),
            ),
        )
    )
    return axis_u, (-axis_u[1], axis_u[0])


def service_connected_queue_domain(domain, service_point: Point):
    """Select one physical queue component, preferring the service-side one."""

    components = [
        geometry
        for geometry in getattr(domain, "geoms", (domain,))
        if getattr(geometry, "geom_type", "") in {"Polygon", "MultiPolygon"}
        and not geometry.is_empty
    ]
    if not components:
        return domain
    point = ShapelyPoint(service_point)
    return min(
        components,
        key=lambda geometry: (
            round(float(geometry.distance(point)), 9),
            -round(float(geometry.area), 9),
            tuple(round(value, 6) for value in geometry.bounds),
        ),
    )


def connect_service_to_queue_slots(
    walkable_geometry,
    service_point: Point,
    queue_slots: tuple[Point, ...],
    *,
    spacing: float,
    capacity: int,
    queue_id: str,
) -> tuple[Point, ...]:
    """Materialize any service bridge inside the declared queue capacity."""

    if not queue_slots:
        return ()
    first_slot = queue_slots[0]
    domain = service_connected_queue_domain(walkable_geometry, first_slot)
    service = ShapelyPoint(service_point)
    if walkable_geometry.covers(service) and not domain.buffer(1e-7).covers(service):
        raise ValueError(
            f"queue {queue_id!r} service point belongs to a disconnected "
            "walkable component"
        )
    body_clearance = min(0.18, float(spacing) * 0.2)
    body_clear_domain = domain.buffer(-body_clearance)
    if body_clear_domain.is_empty:
        raise ValueError(
            f"queue {queue_id!r} service point cannot reach its first slot "
            "through the body-clear walkable domain"
        )
    covered_domain = body_clear_domain.buffer(1e-7)
    maximum_bridge_step = max(0.35, float(spacing) * 1.6)
    if covered_domain.covers(service):
        bridge_start = service_point
        external_distance = 0.0
    else:
        _service, boundary_entry = nearest_points(service, body_clear_domain)
        bridge_start = (float(boundary_entry.x), float(boundary_entry.y))
        external_distance = float(service.distance(boundary_entry))
    maximum_portal_offset = max(
        0.2,
        float(spacing) * 0.75 + body_clearance,
    )
    if external_distance > maximum_portal_offset + 1e-7:
        raise ValueError(
            f"queue {queue_id!r} service point cannot reach its first slot "
            "through the walkable domain"
        )
    for first_index, candidate_first_slot in enumerate(queue_slots):
        bridge_distance = _point_distance(bridge_start, candidate_first_slot)
        bridge_line = LineString((bridge_start, candidate_first_slot))
        if not covered_domain.covers(bridge_line):
            continue
        if bridge_distance <= maximum_bridge_step + 1e-7:
            return queue_slots[first_index : first_index + capacity]

        minimum_segments = int(ceil(bridge_distance / maximum_bridge_step))
        maximum_segments = int(
            floor(
                bridge_distance
                / (MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M)
            )
        )
        if minimum_segments > maximum_segments:
            continue
        segment_count = minimum_segments
        if segment_count + 1 > max(1, int(capacity)):
            break
        bridge_slots = tuple(
            (
                bridge_start[0]
                + (candidate_first_slot[0] - bridge_start[0])
                * segment_index
                / segment_count,
                bridge_start[1]
                + (candidate_first_slot[1] - bridge_start[1])
                * segment_index
                / segment_count,
            )
            for segment_index in range(segment_count)
        )
        queue_tail = queue_slots[
            first_index : first_index + max(0, capacity - segment_count)
        ]
        result = (*bridge_slots, *queue_tail)
        edges = tuple(zip(result, result[1:]))
        if (
            len(result) < capacity
            or not LineString(result).is_simple
            or not all(
                MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
                <= _point_distance(left, right)
                <= maximum_bridge_step + 1e-7
                for left, right in zip(result, result[1:])
            )
            or not all(covered_domain.covers(LineString(edge)) for edge in edges)
            or any(
                segment_distance(left_start, left_end, right_start, right_end)
                < MIN_COMPILED_QUEUE_SPACING_M - QUEUE_CLEARANCE_EPSILON_M
                for left_edge_index, (left_start, left_end) in enumerate(edges)
                for right_start, right_end in edges[left_edge_index + 2 :]
            )
        ):
            continue
        return result
    raise ValueError(
        f"queue {queue_id!r} service bridge cannot fit within declared capacity"
    )


def _normalize(vector: Point) -> Point:
    length = hypot(vector[0], vector[1])
    if length <= 0.001:
        return (1.0, 0.0)
    return vector[0] / length, vector[1] / length


def _point_distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])
