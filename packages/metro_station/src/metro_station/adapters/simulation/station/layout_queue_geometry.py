from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from math import ceil, cos, floor, hypot, radians, sin

from shapely import from_wkb
from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint

from ..design.schema import (
    MAX_COMPILED_QUEUE_CAPACITY,
    MIN_COMPILED_QUEUE_SPACING_M,
    QueueSpec,
)
from ..facilities.process import (
    DEFAULT_FALLBACK_QUEUE_SPACING,
    QueueLayout,
)
from .geometry import (
    dedupe_points,
    project_to_safe_point,
    safe_core,
)
from .layout_queue_candidates import (
    connect_service_to_queue_slots as _connect_service_to_queue_slots,
    queue_slot_candidates as _queue_slot_candidates,
)
from .layout_queue_path import (
    QUEUE_CLEARANCE_EPSILON_M as QUEUE_CLEARANCE_EPSILON_M,
    QUEUE_EXACT_SEARCH_EXPANSION_BUDGET,
    connected_queue_slot_path as _connected_queue_slot_path,
)
from .layout_types import Point


def _queue_layout(
    queue: QueueSpec | None,
    *,
    default_anchor: Point,
    per_row: int,
    walkable_geometry=None,
    fallback_queue_spacing: float = DEFAULT_FALLBACK_QUEUE_SPACING,
) -> QueueLayout:
    if queue is None:
        spacing = float(fallback_queue_spacing)
        slots = _default_queue_slots(
            default_anchor,
            per_row=per_row,
            spacing=spacing,
            walkable_geometry=walkable_geometry,
        )
        if slots:
            return QueueLayout(
                anchor=slots[0],
                per_row=max(1, min(per_row, len(slots))),
                col_step=(0.0, 0.0),
                row_step=(0.0, 0.0),
                slots=slots,
            )
        return QueueLayout(
            anchor=default_anchor,
            per_row=max(1, per_row),
            col_step=(-spacing, 0.0),
            row_step=(0.0, spacing),
        )

    spacing = queue.spacing_m
    slots = _queue_slots_from_geometry(queue, walkable_geometry)
    if slots:
        return QueueLayout(
            anchor=slots[0],
            per_row=max(1, min(per_row, len(slots))),
            col_step=(0.0, 0.0),
            row_step=(0.0, 0.0),
            slots=slots,
        )

    angle = radians(queue.direction_deg)
    col_step = (cos(angle) * spacing, sin(angle) * spacing)
    row_step = (-sin(angle) * spacing, cos(angle) * spacing)
    return QueueLayout(
        anchor=queue.service_point_m,
        per_row=max(1, min(per_row, queue.capacity)),
        col_step=col_step,
        row_step=row_step,
    )


def _queue_layout_with_service_entry_slot(
    layout: QueueLayout,
    service_entry: Point,
    *,
    walkable_geometry=None,
) -> QueueLayout:
    if not layout.slots:
        return replace(layout, anchor=service_entry)

    capacity = len(layout.slots)
    slots = [service_entry]
    first_queue_slot = layout.slots[0]
    spacing = _queue_spacing(layout, service_entry)
    maximum_step = max(0.35, spacing * 1.6)
    bridge_distance = _point_distance(service_entry, first_queue_slot)
    bridge_line = LineString((service_entry, first_queue_slot))
    if walkable_geometry is not None and not walkable_geometry.buffer(1e-7).covers(
        bridge_line
    ):
        raise ValueError(
            "queue service entry cannot reach its first slot through the walkable domain"
        )
    if bridge_distance > maximum_step:
        if walkable_geometry is None:
            raise ValueError(
                "queue service entry is detached from its first connected slot"
            )
        segment_count = int(ceil(bridge_distance / maximum_step))
        if segment_count + 1 > capacity:
            raise ValueError(
                "queue service bridge cannot fit within the declared occupancy capacity"
            )
        for segment_index in range(1, segment_count):
            fraction = segment_index / segment_count
            slots.append(
                (
                    service_entry[0]
                    + (first_queue_slot[0] - service_entry[0]) * fraction,
                    service_entry[1]
                    + (first_queue_slot[1] - service_entry[1]) * fraction,
                )
            )
    for slot in layout.slots:
        if _point_distance(slot, service_entry) <= 0.15:
            continue
        slots.append(slot)
        if len(slots) >= capacity:
            break

    if len(slots) > capacity:
        raise ValueError("queue service bridge exceeded declared occupancy capacity")

    return replace(
        layout,
        anchor=service_entry,
        per_row=max(1, min(layout.per_row, len(slots))),
        slots=tuple(slots),
    )


def _queue_layout_behind_service_entry(
    layout: QueueLayout,
    service_entry: Point,
    service_exit: Point,
    *,
    forward_tolerance: float = 0.15,
    approach_forward: Point | None = None,
) -> QueueLayout:
    """Keep a vertical queue outside the connector's body corridor.

    Generic fallback queue generation samples a disc around the entrance.  For
    a connector this can place alternate queue slots on the travel side of the
    entrance, so queue compaction makes a passenger cross the entrance and then
    reverse direction when service starts.  The connector axis gives us the
    missing semantic: slots must remain on the approach side unless they are
    laterally at least one body spacing outside the connector axis.  The latter
    preserves valid side holding areas without putting bodies in the travel
    corridor.
    """

    forward = _normalize(
        approach_forward
        if approach_forward is not None
        else (service_exit[0] - service_entry[0], service_exit[1] - service_entry[1])
    )
    backward = (-forward[0], -forward[1])
    lateral = (-forward[1], forward[0])
    spacing = _queue_spacing(layout, service_entry)

    if not layout.slots:
        return replace(
            layout,
            anchor=service_entry,
            col_step=_scaled_vector(lateral, spacing),
            row_step=_scaled_vector(backward, spacing),
        )

    slots = tuple(
        point
        for point in layout.slots
        if _point_distance(point, service_entry) > 0.15
        and (
            _forward_progress(point, service_entry, forward) <= forward_tolerance
            or abs(
                (point[0] - service_entry[0]) * lateral[0]
                + (point[1] - service_entry[1]) * lateral[1]
            )
            >= MIN_COMPILED_QUEUE_SPACING_M - 1e-9
        )
    )
    if not slots:
        raise ValueError(
            "vertical queue geometry has no slot on the approach side of its service entry"
        )

    ordered_slots = _order_slots_by_upstream_serpentine(
        slots,
        service_entry=service_entry,
        forward=forward,
        lateral=lateral,
        spacing=spacing,
    )

    return replace(
        layout,
        anchor=ordered_slots[0],
        per_row=max(1, min(layout.per_row, len(ordered_slots))),
        col_step=_scaled_vector(lateral, spacing),
        row_step=_scaled_vector(backward, spacing),
        slots=ordered_slots,
    )


def _order_slots_by_upstream_serpentine(
    slots: tuple[Point, ...],
    *,
    service_entry: Point,
    forward: Point,
    lateral: Point,
    spacing: float,
) -> tuple[Point, ...]:
    """Order a 2-D waiting area as one traversable queue line.

    Projection bands are not sufficient here: when an entrance is laterally
    off-centre, one physical grid row can straddle two bands and make slot 1
    several metres from the entrance.  Build a path on the local slot-neighbour
    graph instead.  Every accepted successor is reachable in one grid move and
    cannot materially move back toward the service entrance.  Candidates that
    would require a jump are deliberately left out; the runtime capacity must
    describe physically connected standing places, not every sampled point in
    a polygon.
    """

    if not slots:
        return ()

    maximum_step = max(0.35, spacing * 1.6)
    depth_tolerance = max(0.05, spacing * 0.25)

    def coordinates(point: Point) -> tuple[float, float]:
        dx = point[0] - service_entry[0]
        dy = point[1] - service_entry[1]
        depth = max(0.0, -(dx * forward[0] + dy * forward[1]))
        lateral_offset = dx * lateral[0] + dy * lateral[1]
        return depth, lateral_offset

    remaining = set(slots)
    first = min(
        remaining,
        key=lambda point: (
            _point_distance(service_entry, point),
            coordinates(point)[0],
            abs(coordinates(point)[1]),
            coordinates(point)[1],
            point,
        ),
    )
    ordered: list[Point] = [first]
    remaining.remove(first)
    previous = first
    previous_depth = coordinates(first)[0]
    while remaining:
        neighbours = [
            point
            for point in remaining
            if _point_distance(previous, point) <= maximum_step
            and coordinates(point)[0] + depth_tolerance >= previous_depth
        ]
        if not neighbours:
            break
        selected = min(
            neighbours,
            key=lambda point: (
                _point_distance(previous, point),
                coordinates(point)[0],
                abs(coordinates(point)[1]),
                coordinates(point)[1],
                point,
            ),
        )
        ordered.append(selected)
        remaining.remove(selected)
        previous = selected
        previous_depth = coordinates(selected)[0]
    return tuple(ordered)


def _forward_progress(point: Point, origin: Point, forward: Point) -> float:
    return (point[0] - origin[0]) * forward[0] + (point[1] - origin[1]) * forward[1]


def _queue_spacing(layout: QueueLayout, service_entry: Point) -> float:
    explicit_steps = [
        hypot(*layout.col_step),
        hypot(*layout.row_step),
    ]
    slot_steps = [
        _point_distance(left, right)
        for left_index, left in enumerate(layout.slots)
        for right in layout.slots[left_index + 1 :]
        if _point_distance(left, right) > 0.15
    ]
    service_distances = [
        _point_distance(point, service_entry)
        for point in layout.slots
        if _point_distance(point, service_entry) > 0.15
    ]
    inferred_steps = slot_steps or service_distances
    candidates = [value for value in (*explicit_steps, *inferred_steps) if value > 0.15]
    return min(candidates, default=DEFAULT_FALLBACK_QUEUE_SPACING)


def _queue_slots_from_geometry(
    queue: QueueSpec,
    walkable_geometry,
) -> tuple[Point, ...]:
    walkable_wkb = (
        None
        if walkable_geometry is None
        else bytes(walkable_geometry.wkb)
    )
    return _cached_queue_slots_from_geometry(queue, walkable_wkb)


@lru_cache(maxsize=512)
def _cached_queue_slots_from_geometry(
    queue: QueueSpec,
    walkable_wkb: bytes | None,
) -> tuple[Point, ...]:
    walkable_geometry = (
        None
        if walkable_wkb is None
        else from_wkb(walkable_wkb)
    )
    if type(queue.capacity) is not int:
        raise ValueError(f"queue capacity {queue.capacity!r} must be an integer")
    if int(queue.capacity) > MAX_COMPILED_QUEUE_CAPACITY:
        raise ValueError(
            f"queue capacity {queue.capacity} exceeds compiler limit "
            f"{MAX_COMPILED_QUEUE_CAPACITY}"
        )
    if float(queue.spacing_m) < MIN_COMPILED_QUEUE_SPACING_M:
        raise ValueError(
            f"queue spacing {queue.spacing_m} is below body-clear compiler minimum "
            f"{MIN_COMPILED_QUEUE_SPACING_M}"
        )
    spacing = max(0.2, float(queue.spacing_m))
    connected: tuple[Point, ...] = ()
    domain = None
    exact_search_budget = [QUEUE_EXACT_SEARCH_EXPANSION_BUDGET]
    base_candidates = _queue_slot_candidates(queue, walkable_geometry)
    phase_candidates = [base_candidates]
    base_points, base_domain = base_candidates
    body_clearance = min(0.18, spacing * 0.2)
    body_clear_domain = base_domain.buffer(-body_clearance)
    area_capacity = max(
        1,
        int(floor(float(body_clear_domain.area) / (spacing * spacing))),
    )
    # This target is independent of the declared queue capacity, preserving
    # stable prefixes, but it does not ask a physically small domain to search
    # for the global 128-slot compiler maximum.
    canonical_target = min(
        MAX_COMPILED_QUEUE_CAPACITY,
        max(len(base_points), area_capacity),
    )
    if canonical_target < MAX_COMPILED_QUEUE_CAPACITY:
        # Neither one lattice phase nor area / spacing**2 is a physical upper
        # bound.  A half-pitch phase can fit an additional strict slot in a
        # small domain, so inspect all bounded phases before freezing the
        # capacity-independent canonical path target.  Large domains that
        # already reach the compiler cap keep the fast lazy path.
        phase_candidates.extend(
            _queue_slot_candidates(
                queue,
                walkable_geometry,
                phase_u=phase_u,
                phase_v=phase_v,
            )
            for phase_u, phase_v in ((0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
        )
        canonical_target = min(
            MAX_COMPILED_QUEUE_CAPACITY,
            max(canonical_target, *(len(candidates) for candidates, _ in phase_candidates)),
        )
    for candidates, candidate_domain in phase_candidates:
        ordered = _sort_queue_slots(list(candidates), queue, candidate_domain)
        candidate_path = _connected_queue_slot_path(
            ordered,
            domain=candidate_domain,
            spacing=spacing,
            target_length=canonical_target,
            service_point=queue.service_point_m,
            exact_search_budget=exact_search_budget,
        )
        if len(candidate_path) > len(connected):
            connected = candidate_path
            domain = candidate_domain
        if len(connected) >= canonical_target:
            break
    if len(connected) < canonical_target:
        if len(phase_candidates) == 1:
            phase_candidates.extend(
                _queue_slot_candidates(
                    queue,
                    walkable_geometry,
                    phase_u=phase_u,
                    phase_v=phase_v,
                )
                for phase_u, phase_v in ((0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
            )
        for candidates, candidate_domain in phase_candidates[1:]:
            ordered = _sort_queue_slots(list(candidates), queue, candidate_domain)
            candidate_path = _connected_queue_slot_path(
                ordered,
                domain=candidate_domain,
                spacing=spacing,
                target_length=canonical_target,
                service_point=queue.service_point_m,
                exact_search_budget=exact_search_budget,
            )
            if len(candidate_path) > len(connected):
                connected = candidate_path
                domain = candidate_domain
            if len(connected) >= canonical_target:
                break
    if len(connected) < canonical_target:
        # Curved narrow passages (for example an annular corridor) may only
        # admit a chain that alternates cardinal and diagonal lattice edges.
        # Even a one-slot deficit is material: another lattice phase can have
        # a complete diagonal path when every cardinal path is one slot short.
        # Keep the diagonal graph as a strict fallback and validate every new
        # edge against the existing non-adjacent chain.
        for candidates, candidate_domain in phase_candidates:
            ordered = _sort_queue_slots(list(candidates), queue, candidate_domain)
            candidate_path = _connected_queue_slot_path(
                ordered,
                domain=candidate_domain,
                spacing=spacing,
                target_length=canonical_target,
                service_point=queue.service_point_m,
                allow_diagonal=True,
                exact_search_budget=exact_search_budget,
            )
            if len(candidate_path) > len(connected):
                connected = candidate_path
                domain = candidate_domain
            if len(connected) >= canonical_target:
                break
    if domain is None:
        return ()
    if connected and walkable_geometry is not None:
        connected = _connect_service_to_queue_slots(
            walkable_geometry,
            queue.service_point_m,
            connected,
            spacing=float(queue.spacing_m),
            capacity=int(queue.capacity),
            queue_id=queue.id,
        )
    return tuple(dedupe_points(connected))[: queue.capacity]


def _sort_queue_slots(
    candidates: list[Point],
    queue: QueueSpec,
    domain,
) -> list[Point]:
    return _sort_queue_slots_from_service(
        candidates,
        queue.service_point_m,
        queue.direction_deg,
        queue.spacing_m,
        domain,
    )


def _sort_queue_slots_from_service(
    candidates: list[Point],
    service: Point,
    direction_deg: float,
    spacing_m: float,
    domain,
) -> list[Point]:
    centroid = domain.centroid
    tail = (float(centroid.x) - service[0], float(centroid.y) - service[1])
    if hypot(*tail) < 0.001:
        angle = radians(direction_deg)
        tail = (cos(angle), sin(angle))
    tail = _normalize(tail)
    lateral_axis = (-tail[1], tail[0])
    spacing = max(0.2, float(spacing_m))

    def directional_key(point: Point) -> tuple[float, float, float, float]:
        dx = point[0] - service[0]
        dy = point[1] - service[1]
        depth = dx * tail[0] + dy * tail[1]
        lateral = dx * lateral_axis[0] + dy * lateral_axis[1]
        return (
            max(0.0, round(depth / spacing)),
            abs(lateral),
            max(0.0, depth),
            lateral,
        )

    # Depth is the primary invariant: compaction must never send a passenger
    # farther from the service point. Within each depth band, alternate the
    # lateral order to form a deterministic serpentine path. This preserves a
    # continuous queue line under rotation without the backtracking produced
    # by an unconstrained nearest-neighbour walk.
    keyed = [(directional_key(point), point) for point in candidates]
    bands: dict[int, list[tuple[float, Point]]] = {}
    for key, point in keyed:
        bands.setdefault(int(key[0]), []).append((key[3], point))
    ordered: list[Point] = []
    for band_index, band in enumerate(sorted(bands)):
        row = sorted(bands[band], key=lambda item: (item[0], item[1]))
        if band_index % 2:
            row.reverse()
        ordered.extend(point for _lateral, point in row)
    return ordered


def _normalize(vector: Point) -> Point:
    length = hypot(vector[0], vector[1])
    if length <= 0.001:
        return (1.0, 0.0)
    return vector[0] / length, vector[1] / length


def _queue_steps_from_facility_geometry(
    position: Point,
    queue_anchor: Point,
    exit_position: Point,
    *,
    col_spacing: float,
    row_spacing: float,
) -> tuple[Point, Point]:
    queue_vector = (
        queue_anchor[0] - position[0],
        queue_anchor[1] - position[1],
    )
    if hypot(*queue_vector) <= 0.001:
        queue_vector = (
            position[0] - exit_position[0],
            position[1] - exit_position[1],
        )
    queue_unit = _normalize(queue_vector)
    col_step = _scaled_vector(queue_unit, col_spacing)
    normals = (
        (-queue_unit[1], queue_unit[0]),
        (queue_unit[1], -queue_unit[0]),
    )
    row_unit = max(normals, key=lambda point: (point[1], point[0]))
    return col_step, _scaled_vector(row_unit, row_spacing)


def _scaled_vector(vector: Point, scale: float) -> Point:
    return (_clean_zero(vector[0] * scale), _clean_zero(vector[1] * scale))


def _clean_zero(value: float) -> float:
    return 0.0 if abs(value) <= 1e-12 else value


def _default_queue_slots(
    anchor: Point,
    *,
    per_row: int,
    spacing: float,
    walkable_geometry,
) -> tuple[Point, ...]:
    if walkable_geometry is None:
        return ()
    local_domain = walkable_geometry.intersection(ShapelyPoint(anchor).buffer(5.0))
    if local_domain.is_empty:
        local_domain = walkable_geometry
    core = safe_core(local_domain, min(0.18, spacing * 0.2))
    min_x, min_y, max_x, max_y = core.bounds
    candidates: list[Point] = []
    y = min_y + spacing / 2.0
    while y <= max_y + 0.001:
        x = min_x + spacing / 2.0
        while x <= max_x + 0.001:
            point = (round(x, 4), round(y, 4))
            if core.covers(ShapelyPoint(point)):
                candidates.append(point)
            x += spacing
        y += spacing

    candidates.sort(key=lambda point: _point_distance(point, anchor))
    count = max(8, min(96, per_row * 4))
    return tuple(dedupe_points(candidates))[:count]


def _jitter_waiting_slots(
    domain,
    slots: tuple[Point, ...],
    *,
    clearance: float,
) -> tuple[Point, ...]:
    if not slots:
        return ()

    jittered: list[Point] = []
    for index, slot in enumerate(slots):
        # Deterministic low-discrepancy offsets keep the waiting distribution natural
        # without changing between runs or pushing people outside the walkable area.
        angle = radians((index * 137.50776405) % 360.0)
        radius = 0.08 + 0.24 * ((index * 37) % 11) / 10.0
        candidate = (
            round(slot[0] + cos(angle) * radius, 4),
            round(slot[1] + sin(angle) * radius, 4),
        )
        if not domain.covers(ShapelyPoint(candidate)):
            candidate = slot
        jittered.append(
            project_to_safe_point(
                domain,
                candidate,
                clearance=clearance,
                require_inside=False,
            )
        )
    return tuple(dedupe_points(jittered))


def _point_distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])
