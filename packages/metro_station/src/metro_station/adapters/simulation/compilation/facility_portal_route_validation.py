from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely.geometry import LineString, Point as ShapelyPoint

from ..design.validation_issue import ValidationIssue, issue
from ..station.facility_portal_binding import FacilityPortalBinding, Point
from .facility_portal_contract import (
    NUMERICAL_TOLERANCE_M,
    PROJECTION_TOLERANCE_M,
    dedupe_issues,
    point_distance,
)
from .geometry_reachability import GeometryCompilePolicy, _ROUTING_ENGINES


def queue_route_issues(
    binding: FacilityPortalBinding,
    navigation_domains: dict[str, Any],
    policy: GeometryCompilePolicy,
    path: str,
) -> list[ValidationIssue]:
    domain = navigation_domains.get(binding.entry_level_id)
    if domain is None or not binding.queue_slots:
        return []
    if binding.queue_region is not None:
        approach_apron = (
            binding.queue_spacing_m * 1.25
            if binding.kind == "train_door"
            else PROJECTION_TOLERANCE_M
        )
        declared_region = binding.queue_region.buffer(approach_apron)
        if any(
            not declared_region.covers(ShapelyPoint(slot))
            for slot in binding.approach_slots
        ):
            return [
                issue(
                    "error",
                    "queues.slot_outside_region",
                    path,
                    "queue slot lies outside its declared queue region",
                )
            ]
    bridge_slots = tuple(
        item.position
        for item in binding.queue_slot_bindings
        if item.role == "bridge"
    )
    points = (binding.entry_point, *bridge_slots, *binding.approach_slots)
    minimum_slot_clearance = policy.two_body_clearance_m
    for left, right in zip(
        binding.approach_slots,
        binding.approach_slots[1:],
        strict=False,
    ):
        if (
            point_distance(left, right) + NUMERICAL_TOLERANCE_M
            >= minimum_slot_clearance
        ):
            continue
        return [
            issue(
                "error",
                "queues.slot_clearance_conflict",
                path,
                "adjacent FIFO slots violate two-body clearance "
                f"{minimum_slot_clearance:.3f} m",
            )
        ]
    maximum_spacing = max(binding.queue_spacing_m * 1.75, 0.5)
    for edge_index, (left, right) in enumerate(
        zip(points, points[1:], strict=False)
    ):
        route_length = _route_length(domain, binding.entry_level_id, left, right)
        if route_length is not None and (
            route_length <= maximum_spacing + PROJECTION_TOLERANCE_M
            or (edge_index == 0 and binding.kind == "elevator")
        ):
            continue
        return [
            issue(
                "error",
                "queues.rank_edge_not_traversable",
                path,
                f"queue rank edge {left!r}->{right!r} is detached or exceeds "
                f"{maximum_spacing:.3f} m",
            )
        ]
    rounded = [
        (round(point[0], 4), round(point[1], 4))
        for point in binding.queue_slots
    ]
    if len(set(rounded)) != len(rounded):
        return [
            issue(
                "error",
                "queues.slot_detached_from_entry",
                path,
                "queue contains duplicate physical slots",
            )
        ]
    if len(binding.approach_slots) >= 3:
        queue_line = LineString(binding.approach_slots)
        if not queue_line.is_simple:
            return [
                issue(
                    "error",
                    "queues.path_self_intersection",
                    path,
                    "compiled FIFO queue path self-intersects",
                )
            ]
        minimum_nonadjacent_clearance = policy.two_body_clearance_m
        edges = tuple(zip(binding.approach_slots, binding.approach_slots[1:]))
        for edge_index, (left_start, left_end) in enumerate(edges):
            left_line = LineString((left_start, left_end))
            for right_start, right_end in edges[edge_index + 2 :]:
                if (
                    left_line.distance(LineString((right_start, right_end)))
                    + NUMERICAL_TOLERANCE_M
                    < minimum_nonadjacent_clearance
                ):
                    return [
                        issue(
                            "error",
                            "queues.slot_clearance_conflict",
                            path,
                            "non-adjacent FIFO edges violate body clearance",
                        )
                    ]
    return []


def cross_binding_slot_issues(
    bindings: tuple[FacilityPortalBinding, ...],
    *,
    minimum_clearance_m: float,
) -> list[ValidationIssue]:
    cell_size = max(NUMERICAL_TOLERANCE_M, float(minimum_clearance_m))
    buckets: dict[
        tuple[str, int, int],
        list[tuple[Point, FacilityPortalBinding]],
    ] = defaultdict(list)
    issues: list[ValidationIssue] = []
    for binding in bindings:
        # Mechanical handoff points may be shared by mutually exclusive
        # elevator facades. Only approach slots are concurrent standing places.
        for slot in binding.approach_slots:
            cell_x = int(slot[0] // cell_size)
            cell_y = int(slot[1] // cell_size)
            for x_offset in (-1, 0, 1):
                for y_offset in (-1, 0, 1):
                    for previous_slot, previous_binding in buckets.get(
                        (
                            binding.entry_level_id,
                            cell_x + x_offset,
                            cell_y + y_offset,
                        ),
                        (),
                    ):
                        if previous_binding.facade_key == binding.facade_key:
                            continue
                        if _bindings_are_mutually_exclusive(
                            previous_binding,
                            binding,
                        ):
                            continue
                        distance = point_distance(previous_slot, slot)
                        if distance <= NUMERICAL_TOLERANCE_M:
                            code = "queues.slot_overlap"
                            message = (
                                "co-active facility facades claim the same physical "
                                "queue slot"
                            )
                        elif distance + NUMERICAL_TOLERANCE_M < minimum_clearance_m:
                            code = "queues.slot_clearance_conflict"
                            message = (
                                "co-active facility queue slots violate two-body "
                                f"clearance {minimum_clearance_m:.3f} m"
                            )
                        else:
                            continue
                        queue_id = binding.queue_id or binding.facility_id
                        issues.append(
                            issue(
                                "error",
                                code,
                                f"queues.{queue_id}",
                                message,
                            )
                        )
            buckets[(binding.entry_level_id, cell_x, cell_y)].append(
                (slot, binding)
            )
    return issues


def validate_portal_binding_configuration(
    bindings: tuple[FacilityPortalBinding, ...],
    *,
    policy: GeometryCompilePolicy,
) -> list[ValidationIssue]:
    """Validate one complete set of facades that may be active together."""

    issues = cross_binding_slot_issues(
        bindings,
        minimum_clearance_m=policy.two_body_clearance_m,
    )
    ids = [binding.facility_id for binding in bindings]
    if len(ids) != len(set(ids)):
        issues.append(
            issue(
                "error",
                "portals.duplicate_binding_id",
                "facilities",
                "an active portal configuration contains duplicate facility IDs",
            )
        )
    return dedupe_issues(issues)


def validate_portal_binding_compatibility(
    bindings: tuple[FacilityPortalBinding, ...],
    *,
    policy: GeometryCompilePolicy,
) -> list[ValidationIssue]:
    """Check every pair of portal variants that can be active together."""

    return dedupe_issues(
        cross_binding_slot_issues(
            bindings,
            minimum_clearance_m=policy.two_body_clearance_m,
        )
    )


def capacity_materialization_issues(
    bindings: tuple[FacilityPortalBinding, ...],
) -> list[ValidationIssue]:
    grouped: dict[str, list[FacilityPortalBinding]] = defaultdict(list)
    for binding in bindings:
        if binding.queue_id is not None:
            grouped[binding.queue_id].append(binding)
    issues: list[ValidationIssue] = []
    for queue_id, queue_bindings in grouped.items():
        declared = max(binding.source_queue_capacity for binding in queue_bindings)
        materialized = sum(len(binding.approach_slots) for binding in queue_bindings)
        if materialized >= declared:
            continue
        issues.append(
            issue(
                "error",
                "queues.capacity_not_materialized",
                f"queues.{queue_id}",
                f"queue declares {declared} places but only {materialized} slots were compiled",
            )
        )
    return issues


def _bindings_are_mutually_exclusive(
    left: FacilityPortalBinding,
    right: FacilityPortalBinding,
) -> bool:
    return bool(
        left.activation_group_id is not None
        and left.activation_group_id == right.activation_group_id
        and left.activation_variant_id != right.activation_variant_id
    )


def _route_length(
    domain: Any,
    level_id: str,
    start: Point,
    target: Point,
) -> float | None:
    if point_distance(start, target) <= 0.001:
        return 0.0
    direct = LineString((start, target))
    safe_domain = domain.buffer(NUMERICAL_TOLERANCE_M)
    if safe_domain.covers(direct):
        return float(direct.length)
    try:
        engine = _ROUTING_ENGINES.get(level_id, safe_domain)
        waypoints = tuple(engine.compute_waypoints(start, target))
    except Exception:
        return None
    if not waypoints or not safe_domain.covers(LineString(waypoints)):
        return None
    return sum(
        point_distance(left, right)
        for left, right in zip(waypoints, waypoints[1:], strict=False)
    )


__all__ = [
    "capacity_materialization_issues",
    "cross_binding_slot_issues",
    "queue_route_issues",
    "validate_portal_binding_compatibility",
    "validate_portal_binding_configuration",
]
