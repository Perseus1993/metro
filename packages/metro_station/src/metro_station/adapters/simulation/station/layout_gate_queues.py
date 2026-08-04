from __future__ import annotations

from math import cos, radians, sin

from shapely.geometry import Point as ShapelyPoint

from ..design.schema import DesignElement, QueueSpec
from ..facilities.process import (
    QueueCrossingGuard,
    QueueLayout,
)
from .geometry import (
    dedupe_points,
)
from .scenario import StationSandboxScenario
from .layout_queue_geometry import (
    _default_queue_slots,
    _normalize,
    _point_distance,
    _queue_slot_candidates,
    _sort_queue_slots_from_service,
)
from .layout_queue_path import connected_queue_slot_path
from .layout_types import Point


def _gate_lane_count(element: DesignElement) -> int:
    return max(1, int(element.capacity or 1))


def _gate_queue_crossing_guard(
    scenario: StationSandboxScenario,
    *,
    enabled: bool,
) -> QueueCrossingGuard:
    return QueueCrossingGuard(
        enabled=enabled,
        tolerance_units=max(0.05, float(scenario.jupedsim_target_radius_units) * 0.25),
        lane_half_width_units=max(
            1.8,
            float(getattr(scenario, "personal_space_units", 0.8)) * 2.5,
            float(scenario.jupedsim_target_radius_units) * 4.0,
        ),
    )


def _gate_lane_positions(
    element: DesignElement,
    lane_count: int,
    position: Point,
    exit_position: Point,
    *,
    queue: QueueSpec | None = None,
    edge_inset_max: float,
) -> tuple[tuple[Point, Point], ...]:
    start_coordinate, end_coordinate = _gate_service_edge_coordinates(
        element,
        queue,
        position,
        exit_position,
    )
    min_x, min_y, max_x, max_y = _gate_local_bounds(element)
    if lane_count <= 1:
        split_axis = _gate_split_axis(element)
        if split_axis == "x":
            coordinate = (min_x + max_x) / 2.0
            return (
                (
                    _gate_from_local(element, (coordinate, start_coordinate)),
                    _gate_from_local(element, (coordinate, end_coordinate)),
                ),
            )
        coordinate = (min_y + max_y) / 2.0
        return (
            (
                _gate_from_local(element, (start_coordinate, coordinate)),
                _gate_from_local(element, (end_coordinate, coordinate)),
            ),
        )

    split_axis = _gate_split_axis(element)
    positions: list[tuple[Point, Point]] = []
    for lane_index in range(lane_count):
        coordinate = _lane_coordinate(
            min_x if split_axis == "x" else min_y,
            max_x if split_axis == "x" else max_y,
            lane_index,
            lane_count,
            edge_inset_max=edge_inset_max,
        )
        if split_axis == "x":
            lane_position = _gate_from_local(element, (coordinate, start_coordinate))
            lane_exit_position = _gate_from_local(element, (coordinate, end_coordinate))
        else:
            lane_position = _gate_from_local(element, (start_coordinate, coordinate))
            lane_exit_position = _gate_from_local(element, (end_coordinate, coordinate))
        positions.append((lane_position, lane_exit_position))
    return tuple(positions)


def _gate_service_edge_coordinates(
    element: DesignElement,
    queue: QueueSpec | None,
    position: Point,
    exit_position: Point,
) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = _gate_local_bounds(element)
    split_axis = _gate_split_axis(element)
    local_position = _gate_to_local(element, position)
    local_exit = _gate_to_local(element, exit_position)
    if split_axis == "x":
        low, high = min_y, max_y
        position_value, exit_value = local_position[1], local_exit[1]
        queue_value = (
            _gate_to_local(element, _queue_geometry_center(queue))[1]
            if queue is not None
            else None
        )
    else:
        low, high = min_x, max_x
        position_value, exit_value = local_position[0], local_exit[0]
        queue_value = (
            _gate_to_local(element, _queue_geometry_center(queue))[0]
            if queue is not None
            else None
        )

    center = (low + high) / 2.0
    if queue_value is not None and abs(queue_value - center) > 0.001:
        start_is_low = queue_value < center
    else:
        start_is_low = exit_value >= position_value
    return (low, high) if start_is_low else (high, low)


def _queue_geometry_center(queue: QueueSpec) -> Point:
    min_x, min_y, max_x, max_y = queue.geometry.bounds()
    return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)


def _gate_lane_queue_layout(
    base_layout: QueueLayout,
    element: DesignElement,
    *,
    queue: QueueSpec | None,
    lane_index: int,
    lane_count: int,
    lane_position: Point,
    walkable_geometry,
    edge_inset_max: float,
    fallback_queue_spacing: float,
    fallback_queue_capacity: int,
) -> QueueLayout:
    if lane_count <= 1:
        return base_layout

    slots = (
        _queue_slots_from_geometry_for_lane(
            queue,
            element,
            lane_index=lane_index,
            lane_count=lane_count,
            service_point=lane_position,
            walkable_geometry=walkable_geometry,
            edge_inset_max=edge_inset_max,
        )
        if queue is not None
        else _layout_slots_for_lane(
            base_layout,
            element,
            lane_index,
            lane_count,
            edge_inset_max=edge_inset_max,
            fallback_queue_capacity=fallback_queue_capacity,
        )
    )
    if not slots:
        slots = _default_queue_slots(
            lane_position,
            per_row=1,
            spacing=fallback_queue_spacing,
            walkable_geometry=walkable_geometry,
        )[: max(1, int(fallback_queue_capacity))]

    if slots:
        ordered = tuple(slots)
        return QueueLayout(
            anchor=ordered[0],
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(0.0, 0.0),
            slots=ordered,
        )

    return QueueLayout(
        anchor=lane_position,
        per_row=1,
        col_step=(0.0, 0.0),
        row_step=(0.0, fallback_queue_spacing),
    )


def _layout_slots_for_lane(
    layout: QueueLayout,
    element: DesignElement,
    lane_index: int,
    lane_count: int,
    *,
    edge_inset_max: float,
    fallback_queue_capacity: int,
) -> tuple[Point, ...]:
    slots = layout.slots or tuple(
        layout.slot(index)
        for index in range(max(max(1, int(fallback_queue_capacity)), lane_count * 4))
    )
    if not slots:
        return ()
    return _points_for_gate_lane(
        slots,
        element,
        lane_index,
        lane_count,
        edge_inset_max=edge_inset_max,
    )


def _queue_slots_from_geometry_for_lane(
    queue: QueueSpec,
    element: DesignElement,
    *,
    lane_index: int,
    lane_count: int,
    service_point: Point,
    walkable_geometry,
    edge_inset_max: float,
) -> tuple[Point, ...]:
    candidates, domain = _queue_slot_candidates(queue, walkable_geometry)
    capacity = max(1, (queue.capacity + lane_count - 1) // lane_count)
    centerline_slots = _parallel_gate_lane_slots(
        queue,
        domain,
        element=element,
        service_point=service_point,
        capacity=capacity,
    )
    if centerline_slots:
        return centerline_slots

    lane_candidates = _points_for_gate_lane(
        candidates,
        element,
        lane_index,
        lane_count,
        edge_inset_max=edge_inset_max,
    )
    if not lane_candidates:
        lane_candidates = tuple(
            sorted(candidates, key=lambda point: _point_distance(point, service_point))
        )
    ordered = tuple(
        dedupe_points(
            _sort_queue_slots_from_service(
                list(lane_candidates),
                service_point,
                queue.direction_deg,
                queue.spacing_m,
                domain,
            )
        )
    )
    return connected_queue_slot_path(
        list(ordered),
        domain=domain,
        spacing=float(queue.spacing_m),
        target_length=capacity,
        service_point=service_point,
        allow_diagonal=True,
    )


def _parallel_gate_lane_slots(
    queue: QueueSpec,
    domain,
    *,
    element: DesignElement,
    service_point: Point,
    capacity: int,
) -> tuple[Point, ...]:
    if capacity <= 0:
        return ()

    spacing = max(0.2, float(queue.spacing_m))
    tail = _gate_lane_tail_direction(
        queue,
        domain,
        element=element,
        service_point=service_point,
    )
    slots: list[Point] = []
    for index in range(capacity):
        depth = spacing * (index + 0.5)
        candidate = (
            round(service_point[0] + tail[0] * depth, 4),
            round(service_point[1] + tail[1] * depth, 4),
        )
        # A lane is a connected one-dimensional queue inside its declared
        # queue domain.  Projecting an overflow point onto the station-wide
        # walkable area can jump across an obstacle into a different room and
        # silently splice two disconnected queue segments together.
        if not domain.covers(ShapelyPoint(candidate)):
            break
        slots.append((round(candidate[0], 4), round(candidate[1], 4)))

    return tuple(dedupe_points(slots))


def _gate_lane_tail_direction(
    queue: QueueSpec,
    domain,
    *,
    element: DesignElement,
    service_point: Point,
) -> Point:
    """Return a lane-parallel queue tail in the gate's local frame.

    A multi-lane bank must not aim every lane at the shared queue-domain
    centroid: that introduces a lateral component and makes all lanes converge
    into one diagonal fan.  The domain decides only which side of the gate is
    the queue side; the gate's service axis decides the direction.
    """

    centroid_local = _gate_to_local(
        element,
        (float(domain.centroid.x), float(domain.centroid.y)),
    )
    service_local = _gate_to_local(element, service_point)
    split_axis = _gate_split_axis(element)
    flow_axis = 1 if split_axis == "x" else 0
    delta = centroid_local[flow_axis] - service_local[flow_axis]
    if abs(delta) <= 0.001:
        configured_angle = radians(
            float(queue.direction_deg) - float(element.geometry.rotation_deg)
        )
        configured_local = (cos(configured_angle), sin(configured_angle))
        delta = configured_local[flow_axis]
    sign = 1.0 if delta >= 0.0 else -1.0
    local_tail = (0.0, sign) if flow_axis == 1 else (sign, 0.0)
    center_world = _gate_from_local(element, (0.0, 0.0))
    tail_world = _gate_from_local(element, local_tail)
    return _normalize(
        (
            tail_world[0] - center_world[0],
            tail_world[1] - center_world[1],
        )
    )


def _points_for_gate_lane(
    points: tuple[Point, ...],
    element: DesignElement,
    lane_index: int,
    lane_count: int,
    *,
    edge_inset_max: float,
) -> tuple[Point, ...]:
    min_x, min_y, max_x, max_y = _gate_local_bounds(element)
    split_axis = _gate_split_axis(element)
    min_value = min_x if split_axis == "x" else min_y
    max_value = max_x if split_axis == "x" else max_y
    lane_values = tuple(
        _lane_coordinate(
            min_value,
            max_value,
            index,
            lane_count,
            edge_inset_max=edge_inset_max,
        )
        for index in range(lane_count)
    )

    selected: list[Point] = []
    axis_index = 0 if split_axis == "x" else 1
    for point in points:
        slot_value = _gate_to_local(element, point)[axis_index]
        nearest_lane = min(
            range(lane_count),
            key=lambda index: abs(slot_value - lane_values[index]),
        )
        if nearest_lane == lane_index:
            selected.append(point)
    return tuple(selected)


def _gate_split_axis(element: DesignElement) -> str:
    min_x, min_y, max_x, max_y = _gate_local_bounds(element)
    return "x" if max_x - min_x >= max_y - min_y else "y"


def _gate_local_bounds(element: DesignElement) -> tuple[float, float, float, float]:
    geometry = element.geometry
    if geometry.shape == "rect":
        return (
            -float(geometry.width_m) / 2.0,
            -float(geometry.height_m) / 2.0,
            float(geometry.width_m) / 2.0,
            float(geometry.height_m) / 2.0,
        )
    min_x, min_y, max_x, max_y = geometry.bounds()
    return (
        min_x - (min_x + max_x) / 2.0,
        min_y - (min_y + max_y) / 2.0,
        max_x - (min_x + max_x) / 2.0,
        max_y - (min_y + max_y) / 2.0,
    )


def _gate_to_local(element: DesignElement, point: Point) -> Point:
    center_x, center_y = element.geometry.center()
    angle = radians(float(element.geometry.rotation_deg))
    dx = point[0] - center_x
    dy = point[1] - center_y
    return (
        dx * cos(angle) + dy * sin(angle),
        -dx * sin(angle) + dy * cos(angle),
    )


def _gate_from_local(element: DesignElement, point: Point) -> Point:
    center_x, center_y = element.geometry.center()
    angle = radians(float(element.geometry.rotation_deg))
    return (
        center_x + point[0] * cos(angle) - point[1] * sin(angle),
        center_y + point[0] * sin(angle) + point[1] * cos(angle),
    )


def _lane_coordinate(
    min_value: float,
    max_value: float,
    lane_index: int,
    lane_count: int,
    *,
    edge_inset_max: float,
) -> float:
    if lane_count <= 1:
        return (min_value + max_value) / 2.0
    span = max_value - min_value
    if abs(span) <= 0.001:
        return min_value
    edge_inset = min(
        max(0.0, float(edge_inset_max)),
        span / max(2.0, lane_count * 2.0),
    )
    if span <= edge_inset * 2.0:
        return min_value + (lane_index + 0.5) * span / lane_count
    usable_span = span - edge_inset * 2.0
    return min_value + edge_inset + lane_index * usable_span / max(1, lane_count - 1)
