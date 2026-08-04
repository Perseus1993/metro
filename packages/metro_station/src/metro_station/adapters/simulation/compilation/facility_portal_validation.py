from __future__ import annotations

from collections import Counter
from math import hypot
from typing import Any, Iterable

from shapely.geometry import Point as ShapelyPoint

from ..design.geometry import element_shape
from ..design.schema import DesignElement, QueueSpec, StationDesignDocument
from ..design.validation_issue import ValidationIssue, issue
from ..facilities.process import FacilitySpec
from ..station.facility_portal_binding import FacilityPortalBinding
from ..station.geometry import level_walkable_geometry
from ..station.layout_gate_queues import (
    _gate_local_bounds,
    _gate_split_axis,
    _gate_to_local,
)
from .facility_portal_contract import (
    NUMERICAL_TOLERANCE_M,
    PROJECTION_TOLERANCE_M,
    dedupe_issues,
    facade_key,
    point_distance,
    queue_for_facility,
    queues_by_owner,
    topology_fingerprint,
)
from .facility_portal_route_validation import (
    capacity_materialization_issues,
    cross_binding_slot_issues,
    queue_route_issues,
)
from .geometry_reachability import GeometryCompilePolicy


def validate_facility_portals(
    document: StationDesignDocument,
    facilities: Iterable[FacilitySpec],
    bindings: tuple[FacilityPortalBinding, ...],
    *,
    policy: GeometryCompilePolicy,
) -> list[ValidationIssue]:
    facility_list = tuple(facilities)
    issues: list[ValidationIssue] = []
    expected_ids = [facility.facility_id for facility in facility_list]
    actual_ids = [binding.facility_id for binding in bindings]
    if len(expected_ids) != len(set(expected_ids)):
        issues.append(
            issue(
                "error",
                "portals.duplicate_facility_id",
                "facilities",
                "facility facade IDs must be unique before portal binding",
            )
        )
    if len(actual_ids) != len(set(actual_ids)):
        issues.append(
            issue(
                "error",
                "portals.duplicate_binding_id",
                "facilities",
                "compiled portal binding facility IDs must be unique",
            )
        )
    if Counter(expected_ids) != Counter(actual_ids):
        issues.append(
            issue(
                "error",
                "portals.missing",
                "facilities",
                "compiled portal binding IDs do not match facility facade IDs one-to-one",
            )
        )
    if len({binding.facade_key for binding in bindings}) != len(bindings):
        issues.append(
            issue(
                "error",
                "portals.missing",
                "facilities",
                "compiled portal bindings contain duplicate facade keys",
            )
        )

    domains = {
        level.id: level_walkable_geometry(document, level.id)
        for level in document.levels
    }
    navigation_domains = {
        level_id: domain.buffer(-policy.agent_radius_m)
        for level_id, domain in domains.items()
    }
    elements = document.element_by_id()
    facility_by_id = {facility.facility_id: facility for facility in facility_list}
    queues_by_element = queues_by_owner(document.queues)
    for binding in bindings:
        path = f"facilities.{binding.facility_id}"
        facility = facility_by_id.get(binding.facility_id)
        if facility is not None:
            issues.extend(
                _binding_identity_issues(
                    binding,
                    facility,
                    queues_by_element.get(binding.source_element_id, ()),
                    path,
                )
            )
        issues.extend(_binding_internal_issues(binding, path))
        if (
            binding.fallback_used
            or binding.queue_id is None
            or not binding.queue_slots
            or not binding.approach_slots
        ):
            issues.append(
                issue(
                    "error",
                    "portals.missing",
                    path,
                    f"facility facade {binding.facade_key!r} lacks a strict queue/portal binding",
                )
            )
        if binding.projection_distance_m > PROJECTION_TOLERANCE_M:
            issues.append(
                issue(
                    "error",
                    "portals.outside_walkable_area",
                    path,
                    f"portal required {binding.projection_distance_m:.3f} m projection; "
                    f"limit is {PROJECTION_TOLERANCE_M:.3f} m",
                )
            )
        issues.extend(_level_issues(binding, elements, navigation_domains, path))
        issues.extend(
            _point_issues(binding, domains, navigation_domains, policy, path)
        )
        element = elements.get(binding.source_element_id)
        if element is not None and element.kind == "gate":
            issues.extend(_gate_facade_issues(binding, element, path))
        issues.extend(queue_route_issues(binding, navigation_domains, policy, path))

    issues.extend(capacity_materialization_issues(bindings))
    issues.extend(
        cross_binding_slot_issues(
            bindings,
            minimum_clearance_m=policy.two_body_clearance_m,
        )
    )
    return dedupe_issues(issues)


def _binding_identity_issues(
    binding: FacilityPortalBinding,
    facility: FacilitySpec,
    owner_queues: tuple[QueueSpec, ...],
    path: str,
) -> list[ValidationIssue]:
    expected_facade_key = facade_key(facility)
    facade_key_matches = (
        binding.facade_key == expected_facade_key
        or binding.facade_key.endswith(
            f"|compiled_reverse:{facility.direction}"
        )
    )
    expected_slots = tuple(
        (float(point[0]), float(point[1]))
        for point in facility.queue_layout.slots
    )
    expected_lane_id = "|".join(
        (binding.queue_id or "unbound", facility.facility_id, facility.direction)
    )
    runtime_queue_slots = (
        binding.approach_slots if facility.kind == "elevator" else expected_slots
    )
    runtime_slot_mapping_matches = all(
        item.runtime_slot_index is None
        or (
            0 <= item.runtime_slot_index < len(runtime_queue_slots)
            and item.position == runtime_queue_slots[item.runtime_slot_index]
        )
        for item in binding.queue_slot_bindings
    )
    slot_identity_matches = all(
        item.slot_id
        == f"{facility.facility_id}:{facility.direction}:source_slot:{source_index}"
        and item.lane_id == expected_lane_id
        for source_index, item in enumerate(binding.queue_slot_bindings)
    )
    identity_matches = (
        facade_key_matches
        and binding.source_element_id == facility.source_element_id
        and binding.stage == facility.stage
        and binding.kind == facility.kind
        and binding.direction == facility.direction
        and binding.entry_point == facility.position
        and binding.exit_point == facility.exit_position
        and binding.entry_level_id
        == (facility.entry_level_id or binding.entry_level_id)
        and binding.exit_level_id
        == (facility.exit_level_id or facility.entry_level_id or binding.exit_level_id)
        and binding.queue_slots == expected_slots
        and runtime_slot_mapping_matches
        and slot_identity_matches
    )
    expected_queue = queue_for_facility(owner_queues, facility)
    if binding.queue_id is not None and binding.queue_id.startswith(
        "compiled_reverse:"
    ):
        # A reversible facade owns a compiler-generated temporary approach
        # lane.  An authored queue for another facade on the same physical
        # escalator may legitimately have the desired direction; it is not
        # the queue claimed by this binding and must not invalidate the
        # synthetic lane's identity.  Cross-binding clearance validation
        # independently rejects spatial conflicts between both lanes.
        queue_matches = True
    else:
        queue_matches = expected_queue is not None and (
            binding.queue_id == expected_queue.id
            and binding.source_queue_capacity == int(expected_queue.capacity)
            and binding.declared_queue_capacity == len(binding.approach_slots)
            and abs(binding.queue_spacing_m - float(expected_queue.spacing_m))
            <= NUMERICAL_TOLERANCE_M
            and binding.queue_region is not None
            and binding.queue_region.equals(element_shape(expected_queue.geometry))
        )
    if identity_matches and queue_matches:
        return []
    return [
        issue(
            "error",
            "portals.binding_identity_mismatch",
            path,
            "portal binding does not match its facility facade and declared queue",
        )
    ]


def _binding_internal_issues(
    binding: FacilityPortalBinding,
    path: str,
) -> list[ValidationIssue]:
    slot_bindings = binding.queue_slot_bindings
    source_indices = binding.approach_source_slot_indices
    runtime_indices = binding.approach_slot_indices
    valid_sources = all(
        0 <= index < len(binding.queue_slots) for index in source_indices
    )
    mapped_approaches = (
        tuple(binding.queue_slots[index] for index in source_indices)
        if valid_sources
        else ()
    )
    waiting_slots = tuple(
        sorted(
            (
                item
                for item in slot_bindings
                if item.role == "waiting"
            ),
            key=lambda item: (
                -1 if item.service_rank is None else item.service_rank
            ),
        )
    )
    issues: list[ValidationIssue] = []
    forward_length = hypot(*binding.release_forward)
    lateral_length = hypot(*binding.release_lateral)
    axes_valid = (
        abs(forward_length - 1.0) <= NUMERICAL_TOLERANCE_M
        and abs(lateral_length - 1.0) <= NUMERICAL_TOLERANCE_M
        and abs(
            binding.release_forward[0] * binding.release_lateral[0]
            + binding.release_forward[1] * binding.release_lateral[1]
        )
        <= NUMERICAL_TOLERANCE_M
        and abs(binding.release_lateral[0] + binding.release_forward[1])
        <= NUMERICAL_TOLERANCE_M
        and abs(binding.release_lateral[1] - binding.release_forward[0])
        <= NUMERICAL_TOLERANCE_M
    )
    if (
        binding.queue_topology_version != 1
        or len(slot_bindings) != len(binding.queue_slots)
        or len({item.slot_id for item in slot_bindings}) != len(slot_bindings)
        or len({item.lane_id for item in waiting_slots}) > 1
        or topology_fingerprint(slot_bindings) != binding.topology_fingerprint
        or not axes_valid
    ):
        issues.append(
            issue(
                "error",
                "queues.topology_missing",
                path,
                "compiled queue topology is missing, duplicated, or has a bad fingerprint",
            )
        )
    if (
        tuple(item.position for item in slot_bindings) != binding.queue_slots
        or len(binding.approach_slots) != len(source_indices) != len(runtime_indices)
        or len(binding.approach_slots) != len(runtime_indices)
        or len(set(source_indices)) != len(source_indices)
        or len(set(runtime_indices)) != len(runtime_indices)
        or not all(index >= 0 for index in runtime_indices)
        or mapped_approaches != binding.approach_slots
        or len(set(binding.approach_slots)) != len(binding.approach_slots)
        or binding.declared_queue_capacity != len(binding.approach_slots)
        or binding.source_queue_capacity < binding.declared_queue_capacity
        or tuple(item.position for item in waiting_slots)
        != binding.approach_slots
        or tuple(item.runtime_slot_index for item in waiting_slots)
        != runtime_indices
        or (
            binding.approach_slots
            and binding.approach_point != binding.approach_slots[-1]
        )
    ):
        issues.append(
            issue(
                "error",
                "queues.slot_projection_mismatch",
                path,
                "legacy queue/approach fields disagree with compiled slots",
            )
        )
    ranks = tuple(item.service_rank for item in waiting_slots)
    if ranks != tuple(range(len(waiting_slots))):
        issues.append(
            issue(
                "error",
                "queues.service_rank_invalid",
                path,
                "occupiable queue service ranks must be unique and dense from zero",
            )
        )
    rows = tuple(item.row_index for item in waiting_slots)
    dense_rows = tuple(range(max(rows, default=-1) + 1))
    row_values = tuple(dict.fromkeys(rows))
    row_positions_valid = all(
        tuple(
            item.position_in_row
            for item in waiting_slots
            if item.row_index == row
        )
        == tuple(
            range(sum(item.row_index == row for item in waiting_slots))
        )
        for row in row_values
    )
    if row_values != dense_rows or not row_positions_valid:
        issues.append(
            issue(
                "error",
                "queues.row_order_invalid",
                path,
                "queue rows and positions within each row must be dense and ordered",
            )
        )
    non_occupiable_slots_valid = all(
        item.service_rank is None
        and item.runtime_slot_index is None
        and item.row_index == -1
        and item.position_in_row == -1
        for item in slot_bindings
        if item.role in {"service_portal", "bridge"}
    )
    if not non_occupiable_slots_valid or any(
        item.role not in {"service_portal", "waiting", "bridge"}
        for item in slot_bindings
    ):
        issues.append(
            issue(
                "error",
                "queues.topology_missing",
                path,
                "queue slot roles do not match their service/runtime indices",
            )
        )
    variant_valid = (
        (
            binding.activation_group_id is None
            and binding.activation_variant_id is None
        )
        or (
            binding.activation_group_id == binding.facility_id
            and binding.activation_variant_id == binding.direction
        )
    )
    if not variant_valid:
        issues.append(
            issue(
                "error",
                "portals.variant_group_invalid",
                path,
                "portal activation group and direction variant are inconsistent",
            )
        )
    return issues


def _level_issues(
    binding: FacilityPortalBinding,
    elements: dict[str, DesignElement],
    domains: dict[str, Any],
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    element = elements.get(binding.source_element_id)
    if binding.entry_level_id not in domains or binding.exit_level_id not in domains:
        issues.append(
            issue(
                "error",
                "portals.level_mismatch",
                path,
                "portal references a level absent from the compiled domain set",
            )
        )
        return issues
    if element is not None:
        allowed = (
            set(element.connects_levels)
            if element.role == "vertical_connector"
            else {element.level_id}
        )
        if binding.entry_level_id not in allowed or binding.exit_level_id not in allowed:
            issues.append(
                issue(
                    "error",
                    "portals.level_mismatch",
                    path,
                    f"portal levels are not declared by {element.id!r}",
                )
            )
        if (
            element.role == "vertical_connector"
            and binding.entry_level_id == binding.exit_level_id
        ):
            issues.append(
                issue(
                    "error",
                    "portals.same_side",
                    path,
                    "vertical facility entry and exit resolve to the same level",
                )
            )
    return issues


def _point_issues(
    binding: FacilityPortalBinding,
    domains: dict[str, Any],
    navigation_domains: dict[str, Any],
    policy: GeometryCompilePolicy,
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entry_domain = navigation_domains.get(binding.entry_level_id)
    exit_domain = navigation_domains.get(binding.exit_level_id)
    entry_points = (
        ("raw entry", binding.raw_entry_point),
        ("entry", binding.entry_point),
        ("approach", binding.approach_point),
    )
    for label, point in entry_points:
        if entry_domain is None or not entry_domain.buffer(
            NUMERICAL_TOLERANCE_M
        ).covers(ShapelyPoint(point)):
            issues.append(
                issue(
                    "error",
                    "portals.outside_walkable_area",
                    path,
                    f"{label} point {point!r} is outside the body-safe entry domain",
                )
            )
    if exit_domain is None or not exit_domain.buffer(
        NUMERICAL_TOLERANCE_M
    ).covers(ShapelyPoint(binding.exit_point)):
        issues.append(
            issue(
                "error",
                "portals.outside_walkable_area",
                path,
                f"exit point {binding.exit_point!r} is outside the body-safe exit domain",
            )
        )
    for slot in binding.queue_slots:
        if entry_domain is not None and entry_domain.buffer(
            NUMERICAL_TOLERANCE_M
        ).covers(ShapelyPoint(slot)):
            continue
        issues.append(
            issue(
                "error",
                "queues.slot_outside_safe_core",
                path,
                f"queue slot {slot!r} is outside the body-safe entry domain",
            )
        )
        break

    raw_entry_domain = domains.get(binding.entry_level_id)
    raw_exit_domain = domains.get(binding.exit_level_id)
    for label, point, domain in (
        ("entry", binding.entry_point, raw_entry_domain),
        ("exit", binding.exit_point, raw_exit_domain),
    ):
        if domain is None:
            continue
        clearance = ShapelyPoint(point).distance(domain.boundary)
        minimum_clearance = policy.agent_radius_m * 2.0
        if clearance + NUMERICAL_TOLERANCE_M >= minimum_clearance:
            continue
        issues.append(
            issue(
                "error",
                "portals.clearance_too_small",
                path,
                f"{label} clearance {clearance:.3f} m is below two-radius "
                f"clearance {minimum_clearance:.3f} m",
            )
        )
    return issues


def _gate_facade_issues(
    binding: FacilityPortalBinding,
    element: DesignElement,
    path: str,
) -> list[ValidationIssue]:
    boundary = element_shape(element.geometry).boundary
    local_entry = _gate_to_local(element, binding.entry_point)
    local_exit = _gate_to_local(element, binding.exit_point)
    min_x, min_y, max_x, max_y = _gate_local_bounds(element)
    if _gate_split_axis(element) == "x":
        entry_axis, exit_axis = local_entry[1], local_exit[1]
        low, high = min_y, max_y
        transverse_match = (
            abs(local_entry[0] - local_exit[0]) <= PROJECTION_TOLERANCE_M
        )
    else:
        entry_axis, exit_axis = local_entry[0], local_exit[0]
        low, high = min_x, max_x
        transverse_match = (
            abs(local_entry[1] - local_exit[1]) <= PROJECTION_TOLERANCE_M
        )
    opposite_edges = (
        min(abs(entry_axis - low), abs(entry_axis - high))
        <= PROJECTION_TOLERANCE_M
        and min(abs(exit_axis - low), abs(exit_axis - high))
        <= PROJECTION_TOLERANCE_M
        and (
            (
                abs(entry_axis - low) <= PROJECTION_TOLERANCE_M
                and abs(exit_axis - high) <= PROJECTION_TOLERANCE_M
            )
            or (
                abs(entry_axis - high) <= PROJECTION_TOLERANCE_M
                and abs(exit_axis - low) <= PROJECTION_TOLERANCE_M
            )
        )
    )
    queue_faces_entry = True
    if binding.queue_region is not None:
        centroid = binding.queue_region.centroid
        queue_point = (float(centroid.x), float(centroid.y))
        queue_faces_entry = point_distance(
            queue_point,
            binding.entry_point,
        ) < point_distance(queue_point, binding.exit_point)
    minimum_depth = max(2.0 * PROJECTION_TOLERANCE_M, 0.05)
    if (
        boundary.distance(ShapelyPoint(binding.entry_point))
        <= PROJECTION_TOLERANCE_M
        and boundary.distance(ShapelyPoint(binding.exit_point))
        <= PROJECTION_TOLERANCE_M
        and opposite_edges
        and transverse_match
        and queue_faces_entry
        and abs(exit_axis - entry_axis) >= minimum_depth
    ):
        return []
    return [
        issue(
            "error",
            "portals.facade_mismatch",
            path,
            "gate portals do not lie on opposite edges of the transformed facility facade",
        )
    ]


__all__ = ["validate_facility_portals"]
