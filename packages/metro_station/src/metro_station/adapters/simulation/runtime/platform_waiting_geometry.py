from __future__ import annotations

from math import hypot

Point = tuple[float, float]


def platform_waiting_slot_sort_key(
    point: Point,
    *,
    passenger,
    exit_staging_anchors: tuple[Point, ...],
    boarding_staging_anchors: tuple[Point, ...],
    queue_access_axes: tuple[tuple[Point, Point], ...],
    fallback_anchors: tuple[Point, ...],
) -> tuple[float, ...]:
    """Order platform storage without changing its certified capacity."""

    if str(getattr(passenger, "intent", "")) == "enter_and_board" and bool(
        getattr(passenger, "_platform_waiting_stall_recovery", False)
    ):
        return (
            -1.0,
            hypot(point[0] - passenger.pos[0], point[1] - passenger.pos[1]),
            0.0,
            point[1],
            point[0],
        )
    if str(getattr(passenger, "intent", "")) == "exit_station" and exit_staging_anchors:
        return _anchor_sort_key(point, exit_staging_anchors)
    if boarding_staging_anchors:
        return _anchor_sort_key(point, boarding_staging_anchors)
    access_keys = []
    for tail, axis in queue_access_axes:
        axis_length = hypot(axis[0], axis[1])
        progress = ((point[0] - tail[0]) * axis[0] + (point[1] - tail[1]) * axis[1]) / axis_length
        access_keys.append(
            (
                0.0 if progress <= 0.0 else 1.0,
                hypot(point[0] - tail[0], point[1] - tail[1]),
                max(0.0, progress),
            )
        )
    if access_keys:
        upstream, tail_distance, downstream_progress = min(access_keys)
        return upstream, tail_distance, downstream_progress, point[1], point[0]
    return _anchor_sort_key(point, fallback_anchors)


def _anchor_sort_key(point: Point, anchors: tuple[Point, ...]) -> tuple[float, ...]:
    return (
        0.0,
        min(
            (hypot(point[0] - anchor[0], point[1] - anchor[1]) for anchor in anchors),
            default=0.0,
        ),
        0.0,
        point[1],
        point[0],
    )


def platform_waiting_slot_is_intent_eligible(
    model,
    point: Point,
    *,
    level_id: str,
    passenger,
) -> bool:
    """Keep entry demand on the paid half-plane after crossing a gate."""

    if str(getattr(passenger, "intent", "")) != "enter_and_board":
        return True
    paid_axes = tuple(
        (
            binding.exit_point,
            (
                binding.exit_point[0] - binding.entry_point[0],
                binding.exit_point[1] - binding.entry_point[1],
            ),
        )
        for binding in (
            *model.layout_graph.facility_portal_bindings,
            *model.layout_graph.facility_portal_binding_variants,
        )
        if binding.stage == "entry_gate"
        and binding.exit_level_id == level_id
        and hypot(
            binding.exit_point[0] - binding.entry_point[0],
            binding.exit_point[1] - binding.entry_point[1],
        )
        > 1e-6
    )
    if not paid_axes:
        return True
    exit_point, axis = min(
        paid_axes,
        key=lambda item: (
            hypot(point[0] - item[0][0], point[1] - item[0][1]),
            item[0],
        ),
    )
    axis_length = hypot(axis[0], axis[1])
    paid_progress = (
        (point[0] - exit_point[0]) * axis[0] + (point[1] - exit_point[1]) * axis[1]
    ) / axis_length
    clearance = max(
        float(model.scenario.jupedsim_target_radius_units),
        float(model.scenario.personal_space_units) * 0.5,
    )
    return paid_progress >= clearance - 1e-9


def platform_waiting_slot_clears_boarding_crossings(
    model,
    point: Point,
    *,
    level_id: str,
) -> bool:
    """Keep a waiting body outside every queue-head-to-train-door crossing."""

    scenario = model.scenario
    clearance = max(
        float(scenario.jupedsim_agent_radius_units) * float(scenario.jupedsim_clearance_multiplier),
        float(scenario.personal_space_units) * 0.75,
    )
    for door in model.boarding_doors:
        binding = model.facility_portal_binding(door.facility_id)
        if binding.entry_level_id != level_id or not binding.approach_slots:
            continue
        if (
            _point_segment_distance(
                point,
                binding.approach_slots[0],
                binding.entry_point,
            )
            < clearance - 1e-9
        ):
            return False
    return True


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    squared_length = dx * dx + dy * dy
    if squared_length <= 1e-18:
        return hypot(point[0] - start[0], point[1] - start[1])
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / squared_length
    ratio = min(1.0, max(0.0, ratio))
    projection = start[0] + ratio * dx, start[1] + ratio * dy
    return hypot(point[0] - projection[0], point[1] - projection[1])


__all__ = [
    "platform_waiting_slot_clears_boarding_crossings",
    "platform_waiting_slot_is_intent_eligible",
    "platform_waiting_slot_sort_key",
]
