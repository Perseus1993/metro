from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, hypot, sqrt
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint
from shapely.ops import unary_union

from ..design.schema import StationDesignDocument
from ..design.validation_issue import ValidationIssue, issue
from ..facilities.process import FacilityKind, FacilitySpec
from ..planning.plan import FacilityStage
from ..station.facility_portal_binding import FacilityPortalBinding, Point
from ..station.geometry import grid_safe_points, level_walkable_geometry
from ..station.graph import StationGraph
from .geometry_reachability import GeometryCompilePolicy
from .release_capacity_geometry import (
    release_candidate_grid,
    release_spacing,
    required_release_bodies,
)

DECISION_HOLDING_RADIUS_M = 6.0
_REGION_BY_STAGE = {
    FacilityStage.ENTRY_GATE.value: "entry_gate_decision",
    FacilityStage.VERTICAL_TRANSFER.value: "vertical_decision",
    FacilityStage.BOARDING_DOOR.value: "boarding_decision",
    FacilityStage.EXIT_GATE.value: "exit_gate_decision",
}


@dataclass(frozen=True)
class DecisionHoldingRegionBinding:
    """Finite, compiled standing-position resource for one decision catchment."""

    region_id: str
    stage: str
    level_id: str
    anchors: tuple[Point, ...]
    slots: tuple[Point, ...]
    domain: Any = field(compare=False, repr=False)


def compile_decision_holding_regions(
    document: StationDesignDocument,
    graph: StationGraph,
    bindings: Iterable[FacilityPortalBinding],
    *,
    policy: GeometryCompilePolicy,
    scenario: Any,
    facilities: Iterable[FacilitySpec] = (),
) -> tuple[DecisionHoldingRegionBinding, ...]:
    """Compile bounded, body-clear holding slots outside owned flow resources."""

    binding_set = tuple(bindings)
    facility_by_id = {facility.facility_id: facility for facility in facilities}
    grouped: dict[tuple[str, str], list[FacilityPortalBinding]] = {}
    for binding in binding_set:
        region_id = _REGION_BY_STAGE.get(binding.stage)
        if region_id is None:
            continue
        grouped.setdefault((region_id, binding.entry_level_id), []).append(binding)

    result: list[DecisionHoldingRegionBinding] = []
    # Holding bodies are stationary JuPedSim targets.  Merely separating body
    # discs (2r) creates a collision-free but operationally immobile crystal:
    # the social-force equilibrium prevents neighbours from threading through
    # it or reaching a newly freed facility.  Compile at the operational
    # personal-space contract used by native waiting targets.
    # Grid points are serialized at finite precision; keep a millimetre of
    # compile margin so rounding cannot move a nominal 0.8 m pair just inside
    # the operational personal-space boundary.
    spacing = max(policy.two_body_clearance_m, policy.personal_space_m) + 0.001
    # A queue owner completes tactical arrival when its centre enters the
    # target-radius disk around an approach portal.  Keeping holding bodies
    # only one body-clearance away from the portal can form a collision ring
    # that makes that disk unreachable, even though every standing point is
    # pairwise valid.  Reserve both the arrival disk and the body clearance so
    # FIFO owners can always physically claim the compiled portal.
    protected_clearance = spacing + policy.target_radius_m
    boundary_clearance = policy.agent_radius_m * 1.05
    walkable_by_level: dict[str, Any] = {}
    protected_by_level: dict[str, Any] = {}
    flow_by_level: dict[str, Any] = {}
    ingress_by_level: dict[str, Any] = {}
    reserved_slots_by_level: dict[str, list[Point]] = {}
    for (region_id, level_id), stage_bindings in sorted(grouped.items()):
        anchors = tuple(sorted({tuple(binding.approach_point) for binding in stage_bindings}))
        if level_id not in walkable_by_level:
            walkable_by_level[level_id] = level_walkable_geometry(
                document,
                level_id,
            ).buffer(-boundary_clearance)
        walkable = walkable_by_level[level_id]
        catchment = MultiPoint(anchors).buffer(DECISION_HOLDING_RADIUS_M)
        domain = walkable.intersection(catchment)

        if level_id not in protected_by_level:
            protected_by_level[level_id] = _protected_facility_resources(
                binding_set,
                facility_by_id,
                level_id,
                protected_clearance=protected_clearance,
                policy=policy,
                scenario=scenario,
            )
        protected = protected_by_level[level_id]
        if level_id not in flow_by_level:
            flow_by_level[level_id] = _main_flow_corridors(
                graph,
                level_id,
                spacing,
            )
        flow_corridors = flow_by_level[level_id]
        if level_id not in ingress_by_level:
            ingress_by_level[level_id] = _facility_ingress_corridors(
                binding_set,
                graph,
                level_id,
                spacing,
            )
        ingress_corridors = ingress_by_level[level_id]
        if not protected.is_empty:
            domain = domain.difference(protected)
        if not flow_corridors.is_empty:
            domain = domain.difference(flow_corridors)
        if not ingress_corridors.is_empty:
            domain = domain.difference(ingress_corridors)
        # Decision regions on the same level may overlap.  They are not
        # mutually exclusive: entering, exiting and transfer passengers can
        # wait at the same time.  Allocate their finite cells from one shared
        # ledger so two individually valid regions never certify the same
        # physical body space.
        previously_reserved = reserved_slots_by_level.get(level_id, ())
        if previously_reserved:
            domain = domain.difference(
                MultiPoint(tuple(previously_reserved)).buffer(spacing)
            )

        slots = tuple(
            sorted(
                grid_safe_points(
                    domain,
                    spacing=spacing,
                    clearance=0.0,
                ),
                key=lambda point: (
                    min(_distance(point, anchor) for anchor in anchors),
                    point[1],
                    point[0],
                ),
            )
        )
        result.append(
            DecisionHoldingRegionBinding(
                region_id=region_id,
                stage=stage_bindings[0].stage,
                level_id=level_id,
                anchors=anchors,
                slots=slots,
                domain=domain,
            )
        )
        reserved_slots_by_level.setdefault(level_id, []).extend(slots)
    return tuple(result)


def validate_decision_holding_regions(
    regions: Iterable[DecisionHoldingRegionBinding],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for region in regions:
        path = f"levels.{region.level_id}.holding.{region.region_id}"
        if region.domain.is_empty or not region.slots:
            issues.append(
                issue(
                    "error",
                    "holding.capacity_empty",
                    path,
                    f"decision holding region {region.region_id!r} on level "
                    f"{region.level_id!r} has no body-clear standing slot",
                )
            )
    return issues


def _protected_facility_points(
    bindings: Iterable[FacilityPortalBinding],
    level_id: str,
) -> tuple[Point, ...]:
    points: set[Point] = set()
    for binding in bindings:
        if binding.entry_level_id == level_id:
            points.update(binding.queue_slots)
            points.update(binding.approach_slots)
            points.add(binding.entry_point)
        if binding.exit_level_id == level_id:
            points.add(binding.exit_point)
    return tuple(sorted(points))


def _protected_facility_resources(
    bindings: Iterable[FacilityPortalBinding],
    facility_by_id: dict[str, FacilitySpec],
    level_id: str,
    *,
    protected_clearance: float,
    policy: GeometryCompilePolicy,
    scenario: Any,
):
    """Reserve complete facility footprints, not only portal centres."""

    binding_set = tuple(bindings)
    points = _protected_facility_points(binding_set, level_id)
    resources: list[Any] = []
    if points:
        resources.append(MultiPoint(points).buffer(protected_clearance))
    for binding in binding_set:
        if binding.exit_level_id != level_id or binding.kind not in {
            FacilityKind.ELEVATOR.value,
            FacilityKind.GATE.value,
        }:
            continue
        facility = facility_by_id.get(binding.facility_id)
        if facility is None:
            continue
        spacing = release_spacing(facility, policy)
        if binding.kind == FacilityKind.GATE.value:
            required = required_release_bodies(
                facility,
                binding,
                scenario,
                spacing,
            )
            clearance = max(
                policy.two_body_clearance_m,
                policy.personal_space_m,
            )
            candidates = release_candidate_grid(
                facility,
                binding,
                spacing,
                required,
                minimum_clearance=clearance,
            )
            resources.append(MultiPoint(candidates).buffer(clearance))
            continue
        elevator = None if facility.vertical_config is None else facility.vertical_config.elevator
        batch_capacity = max(
            1,
            len(binding.approach_slots) if elevator is None else int(elevator.batch_capacity),
        )
        spacing = max(spacing, policy.personal_space_m)
        columns = max(1, ceil(sqrt(batch_capacity)))
        rows = max(1, ceil(batch_capacity / columns))
        forward = binding.release_forward
        lateral = binding.release_lateral
        starts: list[Point] = []
        for index in range(batch_capacity):
            row = index // columns
            column = index % columns
            forward_offset = (row - (rows - 1) / 2.0) * spacing
            lateral_offset = (column - (columns - 1) / 2.0) * spacing
            starts.append(
                (
                    binding.exit_point[0]
                    + forward[0] * forward_offset
                    + lateral[0] * lateral_offset,
                    binding.exit_point[1]
                    + forward[1] * forward_offset
                    + lateral[1] * lateral_offset,
                )
            )
        resources.append(MultiPoint(starts).buffer(protected_clearance))
        forward_distance = spacing * max(
            1,
            int(facility.release_forward_extra),
        )
        resources.append(
            unary_union(
                [
                    LineString(
                        (
                            start,
                            (
                                start[0] + forward[0] * forward_distance,
                                start[1] + forward[1] * forward_distance,
                            ),
                        )
                    ).buffer(protected_clearance, cap_style="round")
                    for start in starts
                ]
            )
        )
    return unary_union(resources) if resources else GeometryCollection()


def _main_flow_corridors(graph: StationGraph, level_id: str, clearance: float):
    lines: list[tuple[Point, Point]] = []
    for edge in graph.edges:
        if edge.kind != "walk" or edge.level_change:
            continue
        source = graph.nodes[edge.from_node]
        target = graph.nodes[edge.to_node]
        if source.level_id != level_id or target.level_id != level_id:
            continue
        if _distance(source.position, target.position) <= 1e-6:
            continue
        lines.append((source.position, target.position))
    if not lines:
        return GeometryCollection()
    return MultiLineString(lines).buffer(clearance)


def _facility_ingress_corridors(
    bindings: Iterable[FacilityPortalBinding],
    graph: StationGraph,
    level_id: str,
    clearance: float,
):
    """Reserve a body-clear continuous path from a catchment into each queue.

    Point-wise portal clearance is insufficient: individually valid holding
    slots can form a cross-section of stationary bodies between the decision
    catchment and a queue tail.  Each compiled queue therefore owns a swept
    ingress corridor along its service ordering, extended through the whole
    decision catchment on the upstream side.
    """

    corridors: list[Any] = []
    for binding in bindings:
        if binding.entry_level_id != level_id:
            continue
        waiting_points = tuple(binding.approach_slots)
        if not waiting_points:
            continue
        entry = tuple(binding.entry_point)
        tail = max(waiting_points, key=lambda point: _distance(entry, point))
        dx = tail[0] - entry[0]
        dy = tail[1] - entry[1]
        length = hypot(dx, dy)
        if length <= 1e-6:
            continue
        upstream = (
            tail[0] + dx / length * DECISION_HOLDING_RADIUS_M,
            tail[1] + dy / length * DECISION_HOLDING_RADIUS_M,
        )
        # Queue layouts may be multi-row or use source-slot ordering, so the
        # tuple's final item is not necessarily its physical tail.  The
        # portal-to-tail axis is the continuous ingress resource; individual
        # off-axis slots already have body-clear point protection above.
        corridors.append(
            MultiLineString(((entry, tail), (tail, upstream))).buffer(clearance)
        )
    gate_banks: dict[tuple[str, str], list[FacilityPortalBinding]] = {}
    for binding in bindings:
        if (
            binding.entry_level_id == level_id
            and binding.kind == FacilityKind.GATE.value
            and binding.approach_slots
        ):
            gate_banks.setdefault(
                (binding.stage, str(binding.source_element_id)),
                [],
            ).append(binding)
    for (stage, _source_element_id), bank in gate_banks.items():
        if len(bank) < 2:
            continue
        representative = bank[0]
        representative_tail = max(
            representative.approach_slots,
            key=lambda point: _distance(representative.entry_point, point),
        )
        axis = (
            representative_tail[0] - representative.entry_point[0],
            representative_tail[1] - representative.entry_point[1],
        )
        axis_length = hypot(axis[0], axis[1])
        if axis_length <= 1e-6:
            continue
        axis_unit = (axis[0] / axis_length, axis[1] / axis_length)
        lateral = (-axis_unit[1], axis_unit[0])
        tails = tuple(
            max(
                binding.approach_slots,
                key=lambda point: _distance(binding.entry_point, point),
            )
            for binding in bank
        )
        lateral_projections = tuple(
            point[0] * lateral[0] + point[1] * lateral[1]
            for point in tails
        )
        longitudinal = sum(
            point[0] * axis_unit[0] + point[1] * axis_unit[1]
            for point in tails
        ) / len(tails) + clearance * 1.5
        start_projection = min(lateral_projections) - DECISION_HOLDING_RADIUS_M
        end_projection = max(lateral_projections) + DECISION_HOLDING_RADIUS_M
        start = (
            axis_unit[0] * longitudinal + lateral[0] * start_projection,
            axis_unit[1] * longitudinal + lateral[1] * start_projection,
        )
        end = (
            axis_unit[0] * longitudinal + lateral[0] * end_projection,
            axis_unit[1] * longitudinal + lateral[1] * end_projection,
        )
        # Multi-lane banks need a continuous tail aisle in addition to the
        # per-lane longitudinal ingress tubes. Holding cells otherwise fill
        # every gap between queues and turn any lateral lane choice into a
        # solid-body crossing.
        corridors.append(LineString((start, end)).buffer(clearance))
        if stage != FacilityStage.ENTRY_GATE.value:
            continue

        # Entry demand reaches the bank from authored station entrances, not
        # from the extension of an individual queue axis. Preserve that
        # approach as one continuous body-free corridor into the same tail
        # aisle used by runtime queue routing. Otherwise finite holding cells
        # can remain valid one by one while closing the entire entrance cross
        # section and stranding passengers whose gate queues are empty.
        mouth_longitudinal = sum(
            point[0] * axis_unit[0] + point[1] * axis_unit[1]
            for point in tails
        ) / len(tails) + clearance
        mouth_min = min(lateral_projections)
        mouth_max = max(lateral_projections)
        for entrance in graph.nodes_matching(kind="entrance"):
            if entrance.level_id != level_id:
                continue
            entrance_projection = (
                entrance.position[0] * lateral[0]
                + entrance.position[1] * lateral[1]
            )
            mouth_projection = min(
                max(entrance_projection, mouth_min),
                mouth_max,
            )
            bank_entry = (
                axis_unit[0] * mouth_longitudinal
                + lateral[0] * mouth_projection,
                axis_unit[1] * mouth_longitudinal
                + lateral[1] * mouth_projection,
            )
            if _distance(entrance.position, bank_entry) <= 1e-6:
                continue
            corridors.append(
                LineString((entrance.position, bank_entry)).buffer(clearance)
            )
    if not corridors:
        return GeometryCollection()
    return unary_union(corridors)


def _distance(left: Point, right: Point) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])


__all__ = [
    "DECISION_HOLDING_RADIUS_M",
    "DecisionHoldingRegionBinding",
    "compile_decision_holding_regions",
    "validate_decision_holding_regions",
]
