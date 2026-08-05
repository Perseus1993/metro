"""Executable adversarial probes for every compiler diagnostic contract.

Each probe is a causal pair: a clean control and a mutant that changes one
declared condition.  Integration probes exercise authored station documents;
component probes isolate dense validator predicates; fault-injection probes
exercise exception-to-diagnostic fallback contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal
from unittest.mock import patch

from shapely.geometry import GeometryCollection, Point as ShapelyPoint, Polygon

from metro_station.adapters.simulation.compilation import (
    facility_portals as facility_portals_module,
)
from metro_station.adapters.simulation.compilation import (
    geometry_reachability as geometry_module,
)
from metro_station.adapters.simulation.compilation.decision_holding_regions import (
    DecisionHoldingRegionBinding,
    validate_decision_holding_regions,
)
from metro_station.adapters.simulation.compilation.facility_portal_contract import (
    topology_fingerprint,
)
from metro_station.adapters.simulation.compilation.facility_portal_route_validation import (
    capacity_materialization_issues,
    cross_binding_slot_issues,
    queue_route_issues,
    validate_portal_binding_configuration,
)
from metro_station.adapters.simulation.compilation.facility_portal_validation import (
    _binding_internal_issues,
    _gate_facade_issues,
    _level_issues,
    _point_issues,
    validate_facility_portals,
)
from metro_station.adapters.simulation.compilation.geometry_reachability import (
    WalkEdgeRoute,
    _detour_issue,
    validate_geometry_reachability,
)
from metro_station.adapters.simulation.compilation import (
    spatial_capacity as spatial_capacity_module,
)
from metro_station.adapters.simulation.compilation.spatial_capacity import (
    CAPACITY_POLICY_VERSION,
    SpatialCapacityCertificate,
    SpatialDemandContract,
    validate_spatial_capacity_certificates,
    validate_spatial_demand_contracts,
)
from metro_station.adapters.simulation.compilation.validation import (
    CompiledStationValidation,
    validate_compiled_station_design,
    validate_station_design,
)
from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    LevelSpec,
    QueueSpec,
    StationDesignDocument,
)
from metro_station.adapters.simulation.design.validation_issue import ValidationIssue
from metro_station.adapters.simulation.station.geometry import level_walkable_geometry
from metro_station.adapters.simulation.station.alighting_source_geometry import (
    materialize_alighting_source_candidates,
)
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario

from .invalid_layout_cases import invalid_layout_cases
from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout


ProbeLayer = Literal["integration", "component", "fault_injection"]
IssueRunner = Callable[[], tuple[ValidationIssue, ...]]


@dataclass(frozen=True)
class CompilationNegativeCase:
    case_id: str
    expected_code: str
    exercise: IssueRunner
    control: IssueRunner
    layer: ProbeLayer
    validator: str
    mutation: str
    changed_fields: tuple[str, ...]
    expected_path: str
    target_emitter_line: int
    target_producer_line: int | None = None
    description: str = ""
    expected_severity: str = "error"
    allowed_codes: tuple[str, ...] = ()
    status: Literal["active"] = "active"

    @property
    def expected_codes(self) -> tuple[str, ...]:
        """Return the target plus explicitly causal companion diagnostics."""

        return tuple(dict.fromkeys((self.expected_code, *self.allowed_codes)))


def _baseline_recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="compilation-adversarial-baseline",
        seed=1,
        archetype="two_level_island",
        entrance_count=1,
        gate_count=1,
        elevator_count=1,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=False,
        asset_density="standard",
        geometry_variant=4,
    )


@lru_cache(maxsize=1)
def _baseline_document() -> StationDesignDocument:
    return generate_layout(_baseline_recipe())


def _scenario(document: StationDesignDocument) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"compile-negative-{document.id}",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="compilation_negative_case",
        sample_hours=1,
        station_design=document,
        audit_enabled=False,
        audit_print_events=False,
    )


@lru_cache(maxsize=1)
def _baseline_compilation() -> CompiledStationValidation:
    document = _baseline_document()
    compiled = validate_compiled_station_design(document, _scenario(document))
    if compiled.issues:
        signatures = tuple(
            (item.severity, item.code, item.path) for item in compiled.issues
        )
        raise AssertionError(f"adversarial baseline is not clean: {signatures!r}")
    if compiled.station_graph is None:
        raise AssertionError("adversarial baseline has no station graph")
    return compiled


def _station_control() -> tuple[ValidationIssue, ...]:
    return tuple(validate_station_design(_baseline_document()))


def _compiled_control() -> tuple[ValidationIssue, ...]:
    return _baseline_compilation().issues


def _portal_control() -> tuple[ValidationIssue, ...]:
    compiled = _baseline_compilation()
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            compiled.facilities,
            compiled.facility_portal_bindings,
            policy=compiled.policy,
        )
    )


def _element_by_id(document: StationDesignDocument) -> dict[str, DesignElement]:
    return {element.id: element for element in document.elements}


def _pick_queue(
    document: StationDesignDocument,
    predicate: Callable[[QueueSpec, DesignElement | None], bool],
) -> QueueSpec:
    elements = _element_by_id(document)
    match = next(
        (
            queue
            for queue in document.queues
            if predicate(queue, elements.get(queue.owner_element_id))
        ),
        None,
    )
    if match is None:
        raise ValueError("queue pattern not found")
    return match


def _remove_entrance_walk_paths(document: StationDesignDocument) -> StationDesignDocument:
    entrance_ids = {
        element.id for element in document.elements if element.kind == "entrance"
    }
    return replace(
        document,
        connections=tuple(
            connection
            for connection in document.connections
            if not (
                connection.source_id in entrance_ids and connection.kind == "walk"
            )
        ),
    )


def _remove_upper_vertical_to_floor_walks(
    document: StationDesignDocument,
) -> StationDesignDocument:
    levels = sorted(document.levels, key=lambda level: level.elevation_m, reverse=True)
    if not levels:
        raise ValueError("no levels in baseline document")
    upper = levels[0]
    floor_ids = {
        element.id
        for element in document.elements
        if element.role == "floor" and element.level_id == upper.id
    }
    vertical_ids = {
        element.id
        for element in document.elements
        if element.role == "vertical_connector"
    }
    removed_ids = {
        connection.id
        for connection in document.connections
        if connection.kind == "walk"
        and connection.source_id in vertical_ids
        and connection.target_id in floor_ids
    }
    if not removed_ids:
        raise ValueError("no matching upper-to-floor walk paths found")
    return replace(
        document,
        connections=tuple(
            connection
            for connection in document.connections
            if connection.id not in removed_ids
        ),
    )


def _legacy_document(case_id: str) -> StationDesignDocument:
    case = next(item for item in invalid_layout_cases() if item.case_id == case_id)
    return case.document


def _legacy_runner(case_id: str) -> IssueRunner:
    def run() -> tuple[ValidationIssue, ...]:
        return tuple(validate_station_design(_legacy_document(case_id)))

    return run


def _graph_enter_path_missing() -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_station_design(_remove_entrance_walk_paths(_baseline_document()))
    )


def _graph_exit_path_missing() -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_station_design(
            _remove_upper_vertical_to_floor_walks(_baseline_document())
        )
    )


def _graph_compile_failed() -> tuple[ValidationIssue, ...]:
    with patch.object(
        StationGraph,
        "from_design",
        side_effect=RuntimeError("injected graph compiler failure"),
    ):
        return tuple(validate_station_design(_baseline_document()))


def _detour_issues(*, detour: bool) -> tuple[ValidationIssue, ...]:
    graph = _baseline_compilation().station_graph
    assert graph is not None
    edge = next(
        item for item in graph.edges if item.kind == "walk" and not item.level_change
    )
    route = WalkEdgeRoute(
        edge=edge,
        source_position=(0.0, 0.0),
        target_position=(1.0, 0.0),
        waypoints=(
            ((0.0, 0.0), (0.0, 10.0), (1.0, 10.0), (1.0, 0.0))
            if detour
            else ((0.0, 0.0), (1.0, 0.0))
        ),
    )
    result = _detour_issue(
        graph,
        route,
        max_detour_ratio=_baseline_compilation().policy.max_detour_ratio,
    )
    return () if result is None else (result,)


def _empty_level_domain() -> tuple[ValidationIssue, ...]:
    document = _baseline_document()
    compiled = _baseline_compilation()
    graph = compiled.station_graph
    assert graph is not None
    empty_level_id = document.levels[0].id
    original = geometry_module.level_walkable_geometry

    def fake_walkable(
        candidate: StationDesignDocument,
        level_id: str,
    ):
        if level_id == empty_level_id:
            return GeometryCollection()
        return original(candidate, level_id)

    with patch.object(
        geometry_module,
        "level_walkable_geometry",
        side_effect=fake_walkable,
    ):
        return tuple(
            validate_geometry_reachability(
                document,
                graph=graph,
                policy=compiled.policy,
            )
        )


def _walk_edge_context():
    document = _baseline_document()
    compiled = _baseline_compilation()
    graph = compiled.station_graph
    assert graph is not None
    for edge in graph.edges:
        if edge.kind != "walk" or edge.level_change:
            continue
        source, target = geometry_module._semantic_edge_endpoints(
            document,
            graph,
            edge,
            agent_radius=compiled.policy.agent_radius_m,
        )
        if source != target:
            return document, graph, edge, source, target
    raise ValueError("baseline has no non-degenerate same-level walk edge")


class _ProbeRoutingEngine:
    def __init__(self, mode: Literal["valid", "raise", "empty"]):
        self.mode = mode

    def compute_waypoints(self, start, target):
        if self.mode == "raise":
            raise RuntimeError("injected waypoint engine failure")
        if self.mode == "empty":
            return ()
        return (start, target)


def _emit_walk_route(route) -> tuple[ValidationIssue, ...]:
    graph = _baseline_compilation().station_graph
    assert graph is not None
    result = geometry_module._route_issue(graph, route)
    return () if result is None else (result,)


def _walk_route_with_domain(domain, *, engine_mode: Literal["valid", "raise", "empty"]):
    document, graph, edge, _source, _target = _walk_edge_context()
    source_level = graph.nodes[edge.from_node].level_id
    with patch.object(
        geometry_module._ROUTING_ENGINES,
        "get",
        return_value=_ProbeRoutingEngine(engine_mode),
    ):
        return geometry_module._route_walk_edge(
            document,
            graph,
            edge,
            {source_level: domain},
            _baseline_compilation().policy.agent_radius_m,
        )


def _walk_route_control() -> tuple[ValidationIssue, ...]:
    _document, _graph, _edge, source, target = _walk_edge_context()
    domain = Polygon(
        (
            (min(source[0], target[0]) - 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, max(source[1], target[1]) + 5.0),
            (min(source[0], target[0]) - 5.0, max(source[1], target[1]) + 5.0),
        )
    )
    return _emit_walk_route(_walk_route_with_domain(domain, engine_mode="valid"))


def _walk_empty_domain_producer() -> tuple[ValidationIssue, ...]:
    return _emit_walk_route(
        _walk_route_with_domain(GeometryCollection(), engine_mode="valid")
    )


def _walk_component_missing_producer() -> tuple[ValidationIssue, ...]:
    _document, _graph, _edge, source, target = _walk_edge_context()
    split_domain = GeometryCollection(
        (ShapelyPoint(source).buffer(0.1), ShapelyPoint(target).buffer(0.1))
    )
    return _emit_walk_route(
        _walk_route_with_domain(split_domain, engine_mode="valid")
    )


def _walk_engine_exception_producer() -> tuple[ValidationIssue, ...]:
    _document, _graph, _edge, source, target = _walk_edge_context()
    domain = Polygon(
        (
            (min(source[0], target[0]) - 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, max(source[1], target[1]) + 5.0),
            (min(source[0], target[0]) - 5.0, max(source[1], target[1]) + 5.0),
        )
    )
    return _emit_walk_route(_walk_route_with_domain(domain, engine_mode="raise"))


def _walk_invalid_waypoints_producer() -> tuple[ValidationIssue, ...]:
    _document, _graph, _edge, source, target = _walk_edge_context()
    domain = Polygon(
        (
            (min(source[0], target[0]) - 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, min(source[1], target[1]) - 5.0),
            (max(source[0], target[0]) + 5.0, max(source[1], target[1]) + 5.0),
            (min(source[0], target[0]) - 5.0, max(source[1], target[1]) + 5.0),
        )
    )
    return _emit_walk_route(_walk_route_with_domain(domain, engine_mode="empty"))


def _holding_control() -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_decision_holding_regions(
            _baseline_compilation().decision_holding_regions
        )
    )


def _holding_capacity_empty() -> tuple[ValidationIssue, ...]:
    region = DecisionHoldingRegionBinding(
        region_id="entry_gate_decision",
        stage="entry_gate",
        level_id="b1_concourse",
        anchors=((1.0, 1.0),),
        slots=(),
        domain=GeometryCollection(),
    )
    return tuple(validate_decision_holding_regions((region,)))


def _capacity_compile_failed() -> tuple[ValidationIssue, ...]:
    with patch.object(
        spatial_capacity_module,
        "compile_spatial_capacity_certificates",
        side_effect=RuntimeError("injected spatial capacity compiler failure"),
    ):
        document = _baseline_document()
        return validate_compiled_station_design(document, _scenario(document)).issues


def _bindings():
    return _baseline_compilation().facility_portal_bindings


def _facilities():
    return _baseline_compilation().facilities


def _binding(*, kind: str | None = None, vertical: bool = False):
    for binding in _bindings():
        if kind is not None and binding.kind != kind:
            continue
        if vertical and binding.entry_level_id == binding.exit_level_id:
            continue
        return binding
    raise ValueError(f"baseline binding not found: kind={kind!r}, vertical={vertical!r}")


def _domains():
    return {
        level.id: level_walkable_geometry(_baseline_document(), level.id)
        for level in _baseline_document().levels
    }


def _navigation_domains():
    radius = _baseline_compilation().policy.agent_radius_m
    return {level_id: domain.buffer(-radius) for level_id, domain in _domains().items()}


def _portal_duplicate_facility_id() -> tuple[ValidationIssue, ...]:
    facilities = _facilities()
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            (*facilities, facilities[0]),
            _bindings(),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_duplicate_binding_id_facade_validator() -> tuple[ValidationIssue, ...]:
    bindings = _bindings()
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            (*bindings, bindings[0]),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_configuration_control() -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_portal_binding_configuration(
            (_bindings()[0],),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_duplicate_binding_id_configuration() -> tuple[ValidationIssue, ...]:
    binding = _bindings()[0]
    return tuple(
        validate_portal_binding_configuration(
            (binding, binding),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_missing_id() -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            _bindings()[:-1],
            policy=_baseline_compilation().policy,
        )
    )


def _portal_missing_duplicate_facade() -> tuple[ValidationIssue, ...]:
    bindings = _bindings()
    mutant = replace(bindings[-1], facade_key=bindings[0].facade_key)
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            (*bindings[:-1], mutant),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_missing_strict_binding() -> tuple[ValidationIssue, ...]:
    bindings = _bindings()
    mutant = replace(bindings[0], fallback_used=True)
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            (mutant, *bindings[1:]),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_compilation_failed() -> tuple[ValidationIssue, ...]:
    with patch.object(
        facility_portals_module,
        "compile_facility_portal_bindings",
        side_effect=RuntimeError("injected portal compiler failure"),
    ):
        document = _baseline_document()
        return validate_compiled_station_design(document, _scenario(document)).issues


def _portal_binding_identity_mismatch() -> tuple[ValidationIssue, ...]:
    bindings = _bindings()
    mutant = replace(bindings[0], facade_key="mutated|facade|identity")
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            (mutant, *bindings[1:]),
            policy=_baseline_compilation().policy,
        )
    )


def _portal_projection_outside() -> tuple[ValidationIssue, ...]:
    bindings = _bindings()
    mutant = replace(bindings[0], projection_distance_m=1.0)
    return tuple(
        validate_facility_portals(
            _baseline_document(),
            _facilities(),
            (mutant, *bindings[1:]),
            policy=_baseline_compilation().policy,
        )
    )


def _point_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return tuple(
        _point_issues(
            binding,
            _domains(),
            _navigation_domains(),
            _baseline_compilation().policy,
            f"facilities.{binding.facility_id}",
        )
    )


def _point_mutation(**changes) -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    mutant = replace(binding, **changes)
    return tuple(
        _point_issues(
            mutant,
            _domains(),
            _navigation_domains(),
            _baseline_compilation().policy,
            f"facilities.{binding.facility_id}",
        )
    )


def _portal_entry_outside() -> tuple[ValidationIssue, ...]:
    return _point_mutation(raw_entry_point=(-100.0, -100.0))


def _portal_exit_outside() -> tuple[ValidationIssue, ...]:
    return _point_mutation(exit_point=(-100.0, -100.0))


def _portal_clearance_too_small() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    level = next(
        item
        for item in _baseline_document().levels
        if item.id == binding.entry_level_id
    )
    min_x, min_y, max_x, max_y = _level_bounds(level)
    radius = _baseline_compilation().policy.agent_radius_m
    boundary_near = (min_x + radius / 2.0, (min_y + max_y) / 2.0)
    return _point_mutation(
        raw_entry_point=boundary_near,
        entry_point=boundary_near,
        approach_point=boundary_near,
    )


def _level_bounds(level: LevelSpec) -> tuple[float, float, float, float]:
    xs, ys = zip(*level.footprint)
    return min(xs), min(ys), max(xs), max(ys)


def _level_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(vertical=True)
    return tuple(
        _level_issues(
            binding,
            _baseline_document().element_by_id(),
            _navigation_domains(),
            f"facilities.{binding.facility_id}",
        )
    )


def _portal_level_absent() -> tuple[ValidationIssue, ...]:
    binding = _binding(vertical=True)
    return tuple(
        _level_issues(
            replace(binding, entry_level_id="missing_level"),
            _baseline_document().element_by_id(),
            _navigation_domains(),
            f"facilities.{binding.facility_id}",
        )
    )


def _portal_level_not_declared() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    other_level = next(
        level.id
        for level in _baseline_document().levels
        if level.id != binding.entry_level_id
    )
    return tuple(
        _level_issues(
            replace(binding, entry_level_id=other_level),
            _baseline_document().element_by_id(),
            _navigation_domains(),
            f"facilities.{binding.facility_id}",
        )
    )


def _portal_same_side() -> tuple[ValidationIssue, ...]:
    binding = _binding(vertical=True)
    return tuple(
        _level_issues(
            replace(binding, exit_level_id=binding.entry_level_id),
            _baseline_document().element_by_id(),
            _navigation_domains(),
            f"facilities.{binding.facility_id}",
        )
    )


def _gate_facade_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    element = _baseline_document().element_by_id()[binding.source_element_id]
    return tuple(
        _gate_facade_issues(
            binding,
            element,
            f"facilities.{binding.facility_id}",
        )
    )


def _portal_facade_mismatch() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    element = _baseline_document().element_by_id()[binding.source_element_id]
    return tuple(
        _gate_facade_issues(
            replace(binding, exit_point=binding.entry_point),
            element,
            f"facilities.{binding.facility_id}",
        )
    )


def _internal_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return tuple(
        _binding_internal_issues(binding, f"facilities.{binding.facility_id}")
    )


def _internal_mutation(mutant) -> tuple[ValidationIssue, ...]:
    return tuple(
        _binding_internal_issues(mutant, f"facilities.{mutant.facility_id}")
    )


def _portal_variant_group_invalid() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return _internal_mutation(
        replace(
            binding,
            activation_group_id="wrong_activation_group",
            activation_variant_id=binding.direction,
        )
    )


def _portal_variant_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return _internal_mutation(
        replace(
            binding,
            activation_group_id=binding.facility_id,
            activation_variant_id=binding.direction,
        )
    )


def _queue_topology_structural() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return _internal_mutation(replace(binding, queue_topology_version=2))


def _queue_topology_role() -> tuple[ValidationIssue, ...]:
    binding = _binding(vertical=True)
    slots = list(binding.queue_slot_bindings)
    index = next(i for i, item in enumerate(slots) if item.role == "service_portal")
    slots[index] = replace(slots[index], role="unknown_role")
    frozen_slots = tuple(slots)
    return _internal_mutation(
        replace(
            binding,
            queue_slot_bindings=frozen_slots,
            topology_fingerprint=topology_fingerprint(frozen_slots),
        )
    )


def _queue_projection_mismatch() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return _internal_mutation(
        replace(binding, approach_point=binding.approach_slots[0])
    )


def _queue_service_rank_invalid() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    slots = list(binding.queue_slot_bindings)
    index = max(i for i, item in enumerate(slots) if item.service_rank is not None)
    slots[index] = replace(slots[index], service_rank=len(binding.approach_slots))
    frozen_slots = tuple(slots)
    return _internal_mutation(
        replace(
            binding,
            queue_slot_bindings=frozen_slots,
            topology_fingerprint=topology_fingerprint(frozen_slots),
        )
    )


def _queue_row_order_invalid() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    slots = list(binding.queue_slot_bindings)
    index = next(i for i, item in enumerate(slots) if item.service_rank is not None)
    slots[index] = replace(slots[index], row_index=2)
    frozen_slots = tuple(slots)
    return _internal_mutation(
        replace(
            binding,
            queue_slot_bindings=frozen_slots,
            topology_fingerprint=topology_fingerprint(frozen_slots),
        )
    )


def _route_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    return tuple(
        queue_route_issues(
            binding,
            _navigation_domains(),
            _baseline_compilation().policy,
            f"facilities.{binding.facility_id}",
        )
    )


def _route_mutation(mutant) -> tuple[ValidationIssue, ...]:
    return tuple(
        queue_route_issues(
            mutant,
            _navigation_domains(),
            _baseline_compilation().policy,
            f"facilities.{mutant.facility_id}",
        )
    )


def _queue_slot_outside_region() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    remote_region = Polygon(
        ((-10.0, -10.0), (-9.0, -10.0), (-9.0, -9.0), (-10.0, -9.0))
    )
    return _route_mutation(replace(binding, queue_region=remote_region))


def _queue_adjacent_clearance_conflict() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    point = binding.approach_slots[0]
    delta = _baseline_compilation().policy.two_body_clearance_m / 2.0
    points = (point, (point[0] + delta, point[1]))
    return _route_mutation(
        replace(binding, queue_region=None, queue_slots=points, approach_slots=points)
    )


def _queue_nonadjacent_clearance_conflict() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    points = ((18.45, 14.2), (19.25, 14.2), (19.25, 13.4), (18.45, 13.95))
    return _route_mutation(
        replace(
            binding,
            entry_point=(18.45, 14.8),
            queue_region=None,
            queue_slots=points,
            approach_slots=points,
            queue_spacing_m=1.0,
        )
    )


def _queue_rank_edge_not_traversable() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    far_slot = ((binding.entry_point[0], binding.entry_point[1] - 5.0),)
    return _route_mutation(
        replace(
            binding,
            queue_region=None,
            queue_slots=far_slot,
            approach_slots=far_slot,
        )
    )


def _queue_slot_detached() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    duplicate_slots = (*binding.queue_slots[:-1], binding.queue_slots[-2])
    return _route_mutation(replace(binding, queue_slots=duplicate_slots))


def _queue_path_self_intersection() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    points = ((18.45, 14.2), (19.25, 13.4), (18.45, 13.4), (19.25, 14.2))
    return _route_mutation(
        replace(
            binding,
            entry_point=(18.45, 14.8),
            queue_region=None,
            queue_slots=points,
            approach_slots=points,
            queue_spacing_m=1.0,
        )
    )


def _queue_slot_outside_safe_core() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    mutant = replace(
        binding,
        queue_slots=(*binding.queue_slots[:-1], (-100.0, -100.0)),
    )
    return tuple(
        _point_issues(
            mutant,
            _domains(),
            _navigation_domains(),
            _baseline_compilation().policy,
            f"facilities.{binding.facility_id}",
        )
    )


def _queue_cross_binding_control() -> tuple[ValidationIssue, ...]:
    bindings = tuple(item for item in _bindings() if item.kind == "gate")[:2]
    return tuple(
        cross_binding_slot_issues(
            bindings,
            minimum_clearance_m=_baseline_compilation().policy.two_body_clearance_m,
        )
    )


def _queue_slot_overlap() -> tuple[ValidationIssue, ...]:
    left, right = tuple(item for item in _bindings() if item.kind == "gate")[:2]
    mutant = replace(right, approach_slots=(left.approach_slots[0],))
    return tuple(
        cross_binding_slot_issues(
            (left, mutant),
            minimum_clearance_m=_baseline_compilation().policy.two_body_clearance_m,
        )
    )


def _queue_cross_binding_clearance_conflict() -> tuple[ValidationIssue, ...]:
    left, right = tuple(item for item in _bindings() if item.kind == "gate")[:2]
    point = left.approach_slots[0]
    clearance = _baseline_compilation().policy.two_body_clearance_m
    mutant = replace(
        right,
        approach_slots=((point[0] + clearance / 2.0, point[1]),),
    )
    return tuple(
        cross_binding_slot_issues(
            (left, mutant),
            minimum_clearance_m=clearance,
        )
    )


def _capacity_control() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    queue_bindings = tuple(
        item for item in _bindings() if item.queue_id == binding.queue_id
    )
    return tuple(capacity_materialization_issues(queue_bindings))


def _queue_capacity_not_materialized() -> tuple[ValidationIssue, ...]:
    binding = _binding(kind="gate")
    queue_bindings = tuple(
        item for item in _bindings() if item.queue_id == binding.queue_id
    )
    materialized = sum(len(item.approach_slots) for item in queue_bindings)
    mutant = replace(
        binding,
        source_queue_capacity=materialized + 1,
    )
    return tuple(
        capacity_materialization_issues(
            (mutant, *tuple(item for item in queue_bindings if item is not binding))
        )
    )


_CERTIFICATE_DOMAIN = Polygon(((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)))
_ALIGHTING_SOURCE_PROBE_DOMAIN = Polygon(
    ((-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0))
)


def _spatial_certificate(
    certificate_id: str,
    *,
    resource_kind: str = "queue",
    owner_id: str | None = None,
    slots: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    swept_paths: tuple[tuple[tuple[float, float], ...], ...] = (),
    required_body_capacity: int | None = 1,
    minimum_clearance_m: float = 1.0,
    policy_version: int = CAPACITY_POLICY_VERSION,
    domain=_CERTIFICATE_DOMAIN,
) -> SpatialCapacityCertificate:
    materialized = len(swept_paths) if resource_kind == "service_corridor" else len(slots)
    return SpatialCapacityCertificate(
        certificate_id=certificate_id,
        resource_kind=resource_kind,
        owner_id=certificate_id if owner_id is None else owner_id,
        level_id="probe_level",
        slots=slots,
        swept_paths=swept_paths,
        certified_body_capacity=materialized,
        certified_person_capacity=materialized,
        required_body_capacity=required_body_capacity,
        minimum_clearance_m=minimum_clearance_m,
        density_bodies_per_m2=0.01 * materialized,
        body_profile_fingerprint="negative-case-body-profile",
        domain_fingerprint="negative-case-domain",
        policy_version=policy_version,
        domain=domain,
    )


def _certificate_issues(
    *certificates: SpatialCapacityCertificate,
) -> tuple[ValidationIssue, ...]:
    return tuple(validate_spatial_capacity_certificates(certificates))


def _single_certificate_control(certificate_id: str) -> tuple[ValidationIssue, ...]:
    return _certificate_issues(_spatial_certificate(certificate_id))


def _capacity_certificate_duplicate_control() -> tuple[ValidationIssue, ...]:
    return _single_certificate_control("duplicate_probe")


def _capacity_certificate_duplicate() -> tuple[ValidationIssue, ...]:
    certificate = _spatial_certificate("duplicate_probe")
    return _certificate_issues(certificate, certificate)


def _capacity_policy_control() -> tuple[ValidationIssue, ...]:
    return _single_certificate_control("policy_probe")


def _capacity_policy_mismatch() -> tuple[ValidationIssue, ...]:
    certificate = _spatial_certificate(
        "policy_probe",
        policy_version=CAPACITY_POLICY_VERSION + 1,
    )
    return _certificate_issues(certificate)


def _required_capacity_issues(
    certificate_id: str,
    *,
    resource_kind: str,
    owner_id: str,
    required: int,
) -> tuple[ValidationIssue, ...]:
    swept_paths = (
        (((0.0, 0.0), (1.0, 0.0)),)
        if resource_kind == "service_corridor"
        else ()
    )
    slots = () if resource_kind == "service_corridor" else ((0.0, 0.0),)
    return _certificate_issues(
        _spatial_certificate(
            certificate_id,
            resource_kind=resource_kind,
            owner_id=owner_id,
            slots=slots,
            swept_paths=swept_paths,
            required_body_capacity=required,
        )
    )


def _required_capacity_control(
    certificate_id: str,
    resource_kind: str,
    owner_id: str,
) -> tuple[ValidationIssue, ...]:
    return _required_capacity_issues(
        certificate_id,
        resource_kind=resource_kind,
        owner_id=owner_id,
        required=1,
    )


def _required_capacity_mutant(
    certificate_id: str,
    resource_kind: str,
    owner_id: str,
) -> tuple[ValidationIssue, ...]:
    return _required_capacity_issues(
        certificate_id,
        resource_kind=resource_kind,
        owner_id=owner_id,
        required=2,
    )


def _empty_certificate_issues(
    certificate_id: str,
    resource_kind: str,
) -> tuple[ValidationIssue, ...]:
    return _certificate_issues(
        _spatial_certificate(
            certificate_id,
            resource_kind=resource_kind,
            slots=(),
            swept_paths=(),
            required_body_capacity=None,
        )
    )


def _empty_certificate_control(
    certificate_id: str,
    resource_kind: str,
) -> tuple[ValidationIssue, ...]:
    swept_paths = (
        (((0.0, 0.0), (1.0, 0.0)),)
        if resource_kind == "service_corridor"
        else ()
    )
    slots = () if resource_kind == "service_corridor" else ((0.0, 0.0),)
    return _certificate_issues(
        _spatial_certificate(
            certificate_id,
            resource_kind=resource_kind,
            slots=slots,
            swept_paths=swept_paths,
            required_body_capacity=None,
        )
    )


def _capacity_geometry_control(certificate_id: str) -> tuple[ValidationIssue, ...]:
    return _certificate_issues(
        _spatial_certificate(
            certificate_id,
            slots=((0.0, 0.0), (2.0, 0.0)),
            required_body_capacity=2,
        )
    )


def _capacity_slot_outside_domain() -> tuple[ValidationIssue, ...]:
    certificate = _spatial_certificate("outside_domain_probe")
    remote_domain = Polygon(((10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0)))
    return _certificate_issues(replace(certificate, domain=remote_domain))


def _capacity_internal_slot_conflict() -> tuple[ValidationIssue, ...]:
    return _certificate_issues(
        _spatial_certificate(
            "internal_conflict_probe",
            slots=((0.0, 0.0), (0.25, 0.0)),
            required_body_capacity=2,
        )
    )


def _capacity_coactive_control() -> tuple[ValidationIssue, ...]:
    return _certificate_issues(
        _spatial_certificate("coactive_left", owner_id="left", slots=((0.0, 0.0),)),
        _spatial_certificate("coactive_right", owner_id="right", slots=((2.0, 0.0),)),
    )


def _capacity_coactive_slot_conflict() -> tuple[ValidationIssue, ...]:
    return _certificate_issues(
        _spatial_certificate("coactive_left", owner_id="left", slots=((0.0, 0.0),)),
        _spatial_certificate("coactive_right", owner_id="right", slots=((0.25, 0.0),)),
    )


def _capacity_alighting_source_control() -> tuple[ValidationIssue, ...]:
    source = _alighting_source_probe_certificate()
    queue = _spatial_certificate(
        "boarding_queue_probe",
        owner_id="boarding_queue",
        slots=((15.0, 15.0),),
        minimum_clearance_m=0.396,
        domain=_ALIGHTING_SOURCE_PROBE_DOMAIN,
    )
    return _certificate_issues(source, queue)


def _capacity_alighting_source_conflict() -> tuple[ValidationIssue, ...]:
    source = _alighting_source_probe_certificate()
    queue = _spatial_certificate(
        "boarding_queue_probe",
        owner_id="boarding_queue",
        slots=(source.slots[0],),
        minimum_clearance_m=0.396,
        domain=_ALIGHTING_SOURCE_PROBE_DOMAIN,
    )
    return _certificate_issues(source, queue)


def _alighting_source_probe_certificate() -> SpatialCapacityCertificate:
    candidates = materialize_alighting_source_candidates(
        (0.0, 0.0),
        (0.0, -4.0),
        _ALIGHTING_SOURCE_PROBE_DOMAIN,
        agent_radius_m=0.18,
        peak_batch=4,
    )
    return _spatial_certificate(
        "alighting_source_probe",
        resource_kind="alighting_source",
        owner_id="alighting_source",
        slots=candidates,
        required_body_capacity=4,
        minimum_clearance_m=0.396,
        domain=_ALIGHTING_SOURCE_PROBE_DOMAIN,
    )


def _demand_contract(
    contract_id: str,
    *,
    resource_kind: str,
    required: int,
    certified: int = 10,
    arrival_bodies: int = 11,
) -> SpatialDemandContract:
    return SpatialDemandContract(
        contract_id=contract_id,
        resource_kind=resource_kind,
        stage="boarding_door" if resource_kind == "platform_waiting" else "entry_gate",
        certificate_ids=("probe",),
        forecast_method="negative_case",
        arrival_bodies=arrival_bodies,
        required_body_capacity=required,
        certified_body_capacity=certified,
        certified_person_capacity=certified,
        horizon_seconds=60.0,
        body_profile_fingerprint="negative-case-body-profile",
    )


def _demand_issues(
    contract_id: str,
    *,
    resource_kind: str,
    required: int,
) -> tuple[ValidationIssue, ...]:
    return tuple(
        validate_spatial_demand_contracts(
            (_demand_contract(contract_id, resource_kind=resource_kind, required=required),)
        )
    )


_EXPECTED_PATH_BY_CASE_ID = {
    "graph_unreachable_node_disconnected_platform": "elements.platform_edge_a",
    "graph_enter_path_missing_reverse_direction": "elements.entrance_a",
    "graph_exit_path_missing_reverse_direction": "elements.platform_edge_a",
    "graph_compile_failed_fault_injection": "connections",
    "geometry_level_domain_disconnected_route": "connections.conn_gates_to_stairs",
    "geometry_level_domain_empty_emitter": "levels.b1_concourse",
    "geometry_walk_edge_not_traversable_authored_endpoint": (
        "connections.conn_platform_to_back_corridor"
    ),
    "geometry_walk_edge_empty_domain_producer": "connections.gate_bank_a",
    "geometry_walk_edge_component_missing_producer": "connections.gate_bank_a",
    "geometry_walk_edge_engine_exception_producer": "connections.gate_bank_a",
    "geometry_walk_edge_invalid_waypoints_producer": "connections.gate_bank_a",
    "geometry_entrance_platform_unreachable_sealed_entrance": "elements.entrance_a",
    "geometry_detour_ratio_exceeded_u_route": "connections.gate_bank_a",
    "holding_capacity_empty_no_slots": (
        "levels.b1_concourse.holding.entry_gate_decision"
    ),
    "capacity_compile_failed_fault_injection": "facilities",
    "capacity_certificate_duplicate_collection": "spatial_capacity",
    "capacity_policy_mismatch_version": "spatial_capacity.policy_probe",
    "release_batch_not_placeable_required_plus_one": (
        "spatial_capacity.release_vertical_probe"
    ),
    "release_capacity_not_materialized_required_plus_one": (
        "spatial_capacity.release_gate_probe"
    ),
    "queues_capacity_not_materialized_certificate_required_plus_one": (
        "spatial_capacity.queue_required_probe"
    ),
    "holding_capacity_below_required_plus_one": (
        "spatial_capacity.holding_required_probe"
    ),
    "platform_capacity_below_required_certificate_plus_one": (
        "spatial_capacity.platform_required_probe"
    ),
    "release_route_not_traversable_required_plus_one": (
        "spatial_capacity.corridor_required_probe"
    ),
    "capacity_demand_exceeds_storage_certificate_plus_one": (
        "spatial_capacity.spawn_required_probe"
    ),
    "release_capacity_not_materialized_empty_apron": (
        "spatial_capacity.release_empty_probe"
    ),
    "corridors_outside_walkable_area_empty_path": (
        "spatial_capacity.corridor_empty_probe"
    ),
    "capacity_certificate_empty_queue": "spatial_capacity.queue_empty_probe",
    "capacity_slot_outside_certificate_domain": (
        "spatial_capacity.outside_domain_probe"
    ),
    "capacity_internal_slot_conflict": "spatial_capacity.internal_conflict_probe",
    "capacity_coactive_slot_conflict": "spatial_capacity.coactive_right",
    "capacity_alighting_source_conflicts_with_boarding_queue": (
        "spatial_capacity.boarding_queue_probe"
    ),
    "platform_capacity_below_required_demand_contract": (
        "spatial_demand.platform_probe"
    ),
    "capacity_demand_exceeds_storage_demand_contract": (
        "spatial_demand.stage_storage_probe"
    ),
    "capacity_forecast_margin_low": "spatial_demand.forecast_probe",
    "portals_duplicate_facility_id": "facilities",
    "portals_duplicate_binding_id_facade_validator": "facilities",
    "portals_duplicate_binding_id_active_configuration": "facilities",
    "portals_missing_id_bijection": "facilities",
    "portals_missing_duplicate_facade_key": "facilities",
    "portals_missing_strict_queue_binding": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "portals_missing_compiler_fault": "facilities",
    "portals_binding_identity_mismatch_facade_key": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "portals_outside_walkable_projection_distance": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "portals_outside_walkable_entry_point": "facilities.entry_gate:gate_bank_a:lane_1",
    "portals_outside_walkable_exit_point": "facilities.entry_gate:gate_bank_a:lane_1",
    "portals_clearance_too_small_boundary_epsilon": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "portals_level_mismatch_absent_domain": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "portals_level_mismatch_element_contract": "facilities.entry_gate:gate_bank_a:lane_1",
    "portals_same_side_vertical_facility": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "portals_facade_mismatch_gate_same_edge": "facilities.entry_gate:gate_bank_a:lane_1",
    "portals_variant_group_invalid_group_id": "facilities.entry_gate:gate_bank_a:lane_1",
    "queues_topology_missing_version": "facilities.entry_gate:gate_bank_a:lane_1",
    "queues_topology_missing_role_contract": (
        "facilities.vertical:down_escalator_a:down:b1_concourse:b2_platform"
    ),
    "queues_slot_projection_mismatch_approach_tail": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_service_rank_invalid_gap": "facilities.entry_gate:gate_bank_a:lane_1",
    "queues_row_order_invalid_gap": "facilities.entry_gate:gate_bank_a:lane_1",
    "queues_slot_outside_region_remote_polygon": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_clearance_conflict_adjacent": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_clearance_conflict_nonadjacent_edges": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_clearance_conflict_cross_binding": "queues.queue_gate_bank_a_in",
    "queues_rank_edge_not_traversable_far_slot": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_detached_duplicate_physical_slot": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_path_self_intersection_bow_tie": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_outside_safe_core_remote_slot": (
        "facilities.entry_gate:gate_bank_a:lane_1"
    ),
    "queues_slot_overlap_cross_binding": "queues.queue_gate_bank_a_in",
    "queues_capacity_not_materialized_declared_plus_one": "queues.queue_gate_bank_a_in",
}


_TARGET_EMITTER_LINE_BY_CASE_ID = {
    "graph_unreachable_node_disconnected_platform": 262,
    "graph_enter_path_missing_reverse_direction": 276,
    "graph_exit_path_missing_reverse_direction": 292,
    "graph_compile_failed_fault_injection": 236,
    "geometry_level_domain_disconnected_route": 449,
    "geometry_level_domain_empty_emitter": 171,
    "geometry_walk_edge_not_traversable_authored_endpoint": 449,
    "geometry_walk_edge_empty_domain_producer": 449,
    "geometry_walk_edge_component_missing_producer": 449,
    "geometry_walk_edge_engine_exception_producer": 449,
    "geometry_walk_edge_invalid_waypoints_producer": 449,
    "geometry_entrance_platform_unreachable_sealed_entrance": 506,
    "geometry_detour_ratio_exceeded_u_route": 475,
    "holding_capacity_empty_no_slots": 171,
    "capacity_compile_failed_fault_injection": 173,
    "capacity_certificate_duplicate_collection": 284,
    "capacity_policy_mismatch_version": 295,
    "release_batch_not_placeable_required_plus_one": 318,
    "release_capacity_not_materialized_required_plus_one": 318,
    "queues_capacity_not_materialized_certificate_required_plus_one": 318,
    "holding_capacity_below_required_plus_one": 318,
    "platform_capacity_below_required_certificate_plus_one": 318,
    "release_route_not_traversable_required_plus_one": 318,
    "capacity_demand_exceeds_storage_certificate_plus_one": 318,
    "release_capacity_not_materialized_empty_apron": 336,
    "corridors_outside_walkable_area_empty_path": 336,
    "capacity_certificate_empty_queue": 336,
    "capacity_slot_outside_certificate_domain": 1319,
    "capacity_internal_slot_conflict": 1347,
    "capacity_coactive_slot_conflict": 1382,
    "capacity_alighting_source_conflicts_with_boarding_queue": 1382,
    "platform_capacity_below_required_demand_contract": 478,
    "capacity_demand_exceeds_storage_demand_contract": 478,
    "capacity_forecast_margin_low": 492,
    "portals_duplicate_facility_id": 51,
    "portals_duplicate_binding_id_facade_validator": 60,
    "portals_duplicate_binding_id_active_configuration": 215,
    "portals_missing_id_bijection": 69,
    "portals_missing_duplicate_facade_key": 78,
    "portals_missing_strict_queue_binding": 117,
    "portals_missing_compiler_fault": 127,
    "portals_binding_identity_mismatch_facade_key": 230,
    "portals_outside_walkable_projection_distance": 126,
    "portals_outside_walkable_entry_point": 469,
    "portals_outside_walkable_exit_point": 480,
    "portals_clearance_too_small_boundary_epsilon": 515,
    "portals_level_mismatch_absent_domain": 411,
    "portals_level_mismatch_element_contract": 427,
    "portals_same_side_vertical_facility": 439,
    "portals_facade_mismatch_gate_same_edge": 584,
    "portals_variant_group_invalid_group_id": 391,
    "queues_topology_missing_version": 291,
    "queues_topology_missing_role_contract": 372,
    "queues_slot_projection_mismatch_approach_tail": 319,
    "queues_service_rank_invalid_gap": 329,
    "queues_row_order_invalid_gap": 352,
    "queues_slot_outside_region_remote_polygon": 40,
    "queues_slot_clearance_conflict_adjacent": 65,
    "queues_slot_clearance_conflict_nonadjacent_edges": 127,
    "queues_slot_clearance_conflict_cross_binding": 188,
    "queues_rank_edge_not_traversable_far_slot": 84,
    "queues_slot_detached_duplicate_physical_slot": 98,
    "queues_path_self_intersection_bow_tie": 109,
    "queues_slot_outside_safe_core_remote_slot": 493,
    "queues_slot_overlap_cross_binding": 188,
    "queues_capacity_not_materialized_declared_plus_one": 254,
}


_TARGET_PRODUCER_LINE_BY_CASE_ID = {
    "geometry_level_domain_disconnected_route": 290,
    "geometry_walk_edge_not_traversable_authored_endpoint": 279,
    "geometry_walk_edge_empty_domain_producer": 266,
    "geometry_walk_edge_component_missing_producer": 292,
    "geometry_walk_edge_engine_exception_producer": 321,
    "geometry_walk_edge_invalid_waypoints_producer": 329,
    "release_batch_not_placeable_required_plus_one": 306,
    "release_capacity_not_materialized_required_plus_one": 308,
    "queues_capacity_not_materialized_certificate_required_plus_one": 312,
    "holding_capacity_below_required_plus_one": 313,
    "platform_capacity_below_required_certificate_plus_one": 314,
    "release_route_not_traversable_required_plus_one": 315,
    "capacity_demand_exceeds_storage_certificate_plus_one": 316,
    "release_capacity_not_materialized_empty_apron": 329,
    "corridors_outside_walkable_area_empty_path": 331,
    "capacity_certificate_empty_queue": 333,
    "platform_capacity_below_required_demand_contract": 473,
    "capacity_demand_exceeds_storage_demand_contract": 475,
    "queues_slot_clearance_conflict_cross_binding": 179,
    "queues_slot_overlap_cross_binding": 173,
}


def _case(
    case_id: str,
    expected_code: str,
    exercise: IssueRunner,
    control: IssueRunner,
    *,
    layer: ProbeLayer,
    validator: str,
    mutation: str,
    changed_fields: tuple[str, ...],
    expected_path_fragment: str,
    description: str,
    expected_severity: str = "error",
    allowed_codes: tuple[str, ...] = (),
) -> CompilationNegativeCase:
    expected_path = _EXPECTED_PATH_BY_CASE_ID[case_id]
    if expected_path_fragment not in expected_path:
        raise AssertionError(
            f"path hint {expected_path_fragment!r} does not match exact contract "
            f"{expected_path!r} for {case_id}"
        )
    return CompilationNegativeCase(
        case_id=case_id,
        expected_code=expected_code,
        exercise=exercise,
        control=control,
        layer=layer,
        validator=validator,
        mutation=mutation,
        changed_fields=changed_fields,
        expected_path=expected_path,
        target_emitter_line=_TARGET_EMITTER_LINE_BY_CASE_ID[case_id],
        target_producer_line=_TARGET_PRODUCER_LINE_BY_CASE_ID.get(case_id),
        description=description,
        expected_severity=expected_severity,
        allowed_codes=allowed_codes,
    )


@lru_cache(maxsize=1)
def compilation_negative_cases() -> tuple[CompilationNegativeCase, ...]:
    """Return executable code-level and emitter-site adversarial probes."""

    station = _station_control
    portal = _portal_control
    internal = _internal_control
    route = _route_control
    return (
        _case(
            "graph_unreachable_node_disconnected_platform",
            "graph.unreachable_node",
            _legacy_runner("platform_disconnected"),
            station,
            layer="integration",
            validator="validation._graph_reachability_issues",
            mutation="disconnect platform component from every entrance",
            changed_fields=("connections",),
            expected_path_fragment="elements.platform_edge_a",
            description="semantic graph contains a physically isolated platform component",
            allowed_codes=("graph.enter_path_missing", "graph.exit_path_missing"),
        ),
        _case(
            "graph_enter_path_missing_reverse_direction",
            "graph.enter_path_missing",
            _graph_enter_path_missing,
            station,
            layer="integration",
            validator="validation._graph_reachability_issues",
            mutation="remove entrance-originating directed walk connections",
            changed_fields=("connections",),
            expected_path_fragment="elements.entrance_a",
            description="undirected reachability remains while directed entry route disappears",
        ),
        _case(
            "graph_exit_path_missing_reverse_direction",
            "graph.exit_path_missing",
            _graph_exit_path_missing,
            station,
            layer="integration",
            validator="validation._graph_reachability_issues",
            mutation="remove upper vertical-to-floor directed walk connections",
            changed_fields=("connections",),
            expected_path_fragment="elements.platform_edge_a",
            description="platform loses every directed route to an exit-gate entry",
        ),
        _case(
            "graph_compile_failed_fault_injection",
            "graph.compile_failed",
            _graph_compile_failed,
            station,
            layer="fault_injection",
            validator="validation._validate_station_topology_with_graph",
            mutation="inject StationGraph.from_design failure",
            changed_fields=("StationGraph.from_design",),
            expected_path_fragment="connections",
            description="graph compiler exception is converted into a stable diagnostic",
        ),
        _case(
            "geometry_level_domain_disconnected_route",
            "geometry.level_domain_disconnected",
            _legacy_runner("narrow_neck_blocks_body_domain"),
            station,
            layer="integration",
            validator="geometry_reachability._route_issue",
            mutation="narrow a walkable neck below body-safe clearance",
            changed_fields=("levels.footprint", "elements.geometry"),
            expected_path_fragment="connections.conn_gates_to_stairs",
            description="a semantic walk edge crosses disconnected geometry components",
        ),
        _case(
            "geometry_level_domain_empty_emitter",
            "geometry.level_domain_disconnected",
            _empty_level_domain,
            station,
            layer="fault_injection",
            validator="geometry_reachability.validate_geometry_reachability",
            mutation="inject an empty compiled walkable domain for one level",
            changed_fields=("level_walkable_geometry",),
            expected_path_fragment="levels.",
            description="level-scoped emitter reports a non-polygonal compiled domain",
        ),
        _case(
            "geometry_walk_edge_not_traversable_authored_endpoint",
            "geometry.walk_edge_not_traversable",
            _legacy_runner("obstacle_on_authored_walk_endpoint"),
            station,
            layer="integration",
            validator="geometry_reachability._route_issue",
            mutation="place an obstacle on an authored walk endpoint",
            changed_fields=("elements.geometry",),
            expected_path_fragment="connections.conn_platform_to_back_corridor",
            description="semantic edge endpoints no longer share a continuous route",
        ),
        _case(
            "geometry_walk_edge_empty_domain_producer",
            "geometry.walk_edge_not_traversable",
            _walk_empty_domain_producer,
            _walk_route_control,
            layer="component",
            validator="geometry_reachability._route_issue",
            mutation="replace the source level navigation domain with an empty geometry",
            changed_fields=("navigation_domain",),
            expected_path_fragment="connections.gate_bank_a",
            description="dynamic producer reports a missing navigation domain",
        ),
        _case(
            "geometry_walk_edge_component_missing_producer",
            "geometry.walk_edge_not_traversable",
            _walk_component_missing_producer,
            _walk_route_control,
            layer="component",
            validator="geometry_reachability._route_issue",
            mutation="split endpoints into distinct non-MultiPolygon components",
            changed_fields=("navigation_domain",),
            expected_path_fragment="connections.gate_bank_a",
            description="dynamic producer reports endpoints with no shared component",
        ),
        _case(
            "geometry_walk_edge_engine_exception_producer",
            "geometry.walk_edge_not_traversable",
            _walk_engine_exception_producer,
            _walk_route_control,
            layer="fault_injection",
            validator="geometry_reachability._route_issue",
            mutation="inject an unexpected waypoint-engine exception",
            changed_fields=("RoutingEngine.compute_waypoints",),
            expected_path_fragment="connections.gate_bank_a",
            description="dynamic producer converts routing failure into a route diagnostic",
        ),
        _case(
            "geometry_walk_edge_invalid_waypoints_producer",
            "geometry.walk_edge_not_traversable",
            _walk_invalid_waypoints_producer,
            _walk_route_control,
            layer="fault_injection",
            validator="geometry_reachability._route_issue",
            mutation="return an empty waypoint sequence from the routing engine",
            changed_fields=("RoutingEngine.compute_waypoints",),
            expected_path_fragment="connections.gate_bank_a",
            description="dynamic producer rejects an invalid waypoint result",
        ),
        _case(
            "geometry_entrance_platform_unreachable_sealed_entrance",
            "geometry.entrance_platform_unreachable",
            _legacy_runner("entrance_sealed_from_continuous_domain"),
            station,
            layer="integration",
            validator="geometry_reachability._entrance_platform_issues",
            mutation="seal the entrance from all continuous-space walk edges",
            changed_fields=("elements.geometry",),
            expected_path_fragment="elements.entrance_a",
            description="topological entry route survives but all geometric routes fail",
            allowed_codes=("geometry.walk_edge_not_traversable",),
        ),
        _case(
            "geometry_detour_ratio_exceeded_u_route",
            "geometry.detour_ratio_exceeded",
            lambda: _detour_issues(detour=True),
            lambda: _detour_issues(detour=False),
            layer="component",
            validator="geometry_reachability._detour_issue",
            mutation="replace a direct route by a long U-shaped waypoint route",
            changed_fields=("WalkEdgeRoute.waypoints",),
            expected_path_fragment="connections.",
            description="route remains traversable but exceeds the detour policy",
            expected_severity="warning",
        ),
        _case(
            "holding_capacity_empty_no_slots",
            "holding.capacity_empty",
            _holding_capacity_empty,
            _holding_control,
            layer="component",
            validator="decision_holding_regions.validate_decision_holding_regions",
            mutation="replace holding domain and slots with an empty finite resource",
            changed_fields=("domain", "slots"),
            expected_path_fragment="levels.b1_concourse.holding.entry_gate_decision",
            description="decision catchment cannot materialize a body-clear standing slot",
        ),
        _case(
            "capacity_compile_failed_fault_injection",
            "capacity.compile_failed",
            _capacity_compile_failed,
            _compiled_control,
            layer="fault_injection",
            validator="validation.validate_compiled_station_design",
            mutation="inject spatial-capacity compiler failure",
            changed_fields=("compile_spatial_capacity_certificates",),
            expected_path_fragment="facilities",
            description="capacity compiler exception is converted into a stable diagnostic",
        ),
        _case(
            "capacity_certificate_duplicate_collection",
            "capacity.certificate_duplicate",
            _capacity_certificate_duplicate,
            _capacity_certificate_duplicate_control,
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="append the same certificate a second time",
            changed_fields=("certificates",),
            expected_path_fragment="spatial_capacity",
            description="certificate identities are unique within a compiled resource ledger",
        ),
        _case(
            "capacity_policy_mismatch_version",
            "capacity.policy_mismatch",
            _capacity_policy_mismatch,
            _capacity_policy_control,
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="increment the certificate policy version",
            changed_fields=("policy_version",),
            expected_path_fragment="spatial_capacity.policy_probe",
            description="runtime never consumes a certificate compiled under another policy",
        ),
        _case(
            "release_batch_not_placeable_required_plus_one",
            "release.batch_not_placeable",
            lambda: _required_capacity_mutant(
                "release_vertical_probe", "release_apron", "vertical:probe"
            ),
            lambda: _required_capacity_control(
                "release_vertical_probe", "release_apron", "vertical:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise vertical release demand one body above its constructive proof",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.release_vertical_probe",
            description="a vertical batch cannot exceed its compiled release placement prefix",
        ),
        _case(
            "release_capacity_not_materialized_required_plus_one",
            "release.capacity_not_materialized",
            lambda: _required_capacity_mutant(
                "release_gate_probe", "release_apron", "gate:probe"
            ),
            lambda: _required_capacity_control(
                "release_gate_probe", "release_apron", "gate:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise non-vertical release demand one above materialized slots",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.release_gate_probe",
            description="a service release apron must materialize every admitted body",
        ),
        _case(
            "queues_capacity_not_materialized_certificate_required_plus_one",
            "queues.capacity_not_materialized",
            lambda: _required_capacity_mutant(
                "queue_required_probe", "queue", "queue:probe"
            ),
            lambda: _required_capacity_control(
                "queue_required_probe", "queue", "queue:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise queue demand one above its certified standing slots",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.queue_required_probe",
            description="the capacity ledger independently enforces queue materialization",
        ),
        _case(
            "holding_capacity_below_required_plus_one",
            "holding.capacity_below_required",
            lambda: _required_capacity_mutant(
                "holding_required_probe", "decision_holding", "holding:probe"
            ),
            lambda: _required_capacity_control(
                "holding_required_probe", "decision_holding", "holding:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise holding demand one above its certified standing slots",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.holding_required_probe",
            description="decision holding admission is bounded by constructive storage",
        ),
        _case(
            "platform_capacity_below_required_certificate_plus_one",
            "platform.capacity_below_required",
            lambda: _required_capacity_mutant(
                "platform_required_probe", "platform_waiting", "platform:probe"
            ),
            lambda: _required_capacity_control(
                "platform_required_probe", "platform_waiting", "platform:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise platform demand one above its certified waiting cells",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.platform_required_probe",
            description="platform occupancy cannot exceed its static waiting certificate",
        ),
        _case(
            "release_route_not_traversable_required_plus_one",
            "release.route_not_traversable",
            lambda: _required_capacity_mutant(
                "corridor_required_probe", "service_corridor", "corridor:probe"
            ),
            lambda: _required_capacity_control(
                "corridor_required_probe", "service_corridor", "corridor:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise corridor batch demand above its swept-path proof",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.corridor_required_probe",
            description="release admission requires a traversable swept path per body",
        ),
        _case(
            "capacity_demand_exceeds_storage_certificate_plus_one",
            "capacity.demand_exceeds_storage",
            lambda: _required_capacity_mutant(
                "spawn_required_probe", "spawn_reservoir", "spawn:probe"
            ),
            lambda: _required_capacity_control(
                "spawn_required_probe", "spawn_reservoir", "spawn:probe"
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="raise generic storage demand above its certified reservoir",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_capacity.spawn_required_probe",
            description="all storage resource kinds fail closed when demand exceeds proof",
        ),
        _case(
            "release_capacity_not_materialized_empty_apron",
            "release.capacity_not_materialized",
            lambda: _empty_certificate_issues("release_empty_probe", "release_apron"),
            lambda: _empty_certificate_control("release_empty_probe", "release_apron"),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="remove every release-apron placement",
            changed_fields=("slots", "certified_body_capacity", "certified_person_capacity"),
            expected_path_fragment="spatial_capacity.release_empty_probe",
            description="an empty release apron is rejected even without scenario demand",
        ),
        _case(
            "corridors_outside_walkable_area_empty_path",
            "corridors.outside_walkable_area",
            lambda: _empty_certificate_issues("corridor_empty_probe", "service_corridor"),
            lambda: _empty_certificate_control("corridor_empty_probe", "service_corridor"),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="remove every service-corridor swept path",
            changed_fields=("swept_paths", "certified_body_capacity", "certified_person_capacity"),
            expected_path_fragment="spatial_capacity.corridor_empty_probe",
            description="an empty corridor proof cannot authorize runtime routing",
        ),
        _case(
            "capacity_certificate_empty_queue",
            "capacity.certificate_empty",
            lambda: _empty_certificate_issues("queue_empty_probe", "queue"),
            lambda: _empty_certificate_control("queue_empty_probe", "queue"),
            layer="component",
            validator="spatial_capacity.validate_spatial_capacity_certificates",
            mutation="remove every generic storage placement",
            changed_fields=("slots", "certified_body_capacity", "certified_person_capacity"),
            expected_path_fragment="spatial_capacity.queue_empty_probe",
            description="a zero-capacity storage certificate fails closed",
        ),
        _case(
            "capacity_slot_outside_certificate_domain",
            "capacity.slot_outside_certificate_domain",
            _capacity_slot_outside_domain,
            lambda: _single_certificate_control("outside_domain_probe"),
            layer="component",
            validator="spatial_capacity._certificate_geometry_issues",
            mutation="move the certificate domain away from its certified slot",
            changed_fields=("domain",),
            expected_path_fragment="spatial_capacity.outside_domain_probe",
            description="every constructive standing point lies in its resource domain",
        ),
        _case(
            "capacity_internal_slot_conflict",
            "capacity.internal_slot_conflict",
            _capacity_internal_slot_conflict,
            lambda: _capacity_geometry_control("internal_conflict_probe"),
            layer="component",
            validator="spatial_capacity._certificate_geometry_issues",
            mutation="move one slot inside another slot's body-clearance disk",
            changed_fields=("slots",),
            expected_path_fragment="spatial_capacity.internal_conflict_probe",
            description="one resource cannot count mutually conflicting placements",
        ),
        _case(
            "capacity_coactive_slot_conflict",
            "capacity.coactive_slot_conflict",
            _capacity_coactive_slot_conflict,
            _capacity_coactive_control,
            layer="component",
            validator="spatial_capacity._coactive_certificate_issues",
            mutation="move two co-active owners inside their shared body clearance",
            changed_fields=("slots",),
            expected_path_fragment="spatial_capacity.coactive_right",
            description="co-active resources cannot double-book the same physical space",
        ),
        _case(
            "capacity_alighting_source_conflicts_with_boarding_queue",
            "capacity.coactive_slot_conflict",
            _capacity_alighting_source_conflict,
            _capacity_alighting_source_control,
            layer="component",
            validator="spatial_capacity._coactive_certificate_issues",
            mutation="move a boarding holding slot onto the compiled alighting source lattice",
            changed_fields=("resource_kind", "slots"),
            expected_path_fragment="spatial_capacity.boarding_queue_probe",
            description="runtime alighting source cells cannot share a co-active boarding holding slot",
        ),
        _case(
            "platform_capacity_below_required_demand_contract",
            "platform.capacity_below_required",
            lambda: _demand_issues(
                "platform_probe", resource_kind="platform_waiting", required=11
            ),
            lambda: _demand_issues(
                "platform_probe", resource_kind="platform_waiting", required=5
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_demand_contracts",
            mutation="raise platform forecast above certified waiting capacity",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_demand.platform_probe",
            description="train-service backlog must fit the certified platform store",
        ),
        _case(
            "capacity_demand_exceeds_storage_demand_contract",
            "capacity.demand_exceeds_storage",
            lambda: _demand_issues(
                "stage_storage_probe", resource_kind="stage_storage", required=11
            ),
            lambda: _demand_issues(
                "stage_storage_probe", resource_kind="stage_storage", required=5
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_demand_contracts",
            mutation="raise stage forecast above certified storage capacity",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_demand.stage_storage_probe",
            description="scenario demand cannot silently overflow static stage storage",
        ),
        _case(
            "capacity_forecast_margin_low",
            "capacity.forecast_margin_low",
            lambda: _demand_issues(
                "forecast_probe", resource_kind="stage_storage", required=9
            ),
            lambda: _demand_issues(
                "forecast_probe", resource_kind="stage_storage", required=5
            ),
            layer="component",
            validator="spatial_capacity.validate_spatial_demand_contracts",
            mutation="reduce forecast margin to the policy warning band",
            changed_fields=("required_body_capacity",),
            expected_path_fragment="spatial_demand.forecast_probe",
            description="near-saturation remains executable but produces a stable warning",
            expected_severity="warning",
        ),
        _case(
            "portals_duplicate_facility_id",
            "portals.duplicate_facility_id",
            _portal_duplicate_facility_id,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="append a duplicate facility facade ID",
            changed_fields=("facilities",),
            expected_path_fragment="facilities",
            description="facility facade identities must be unique before binding",
            allowed_codes=("portals.missing",),
        ),
        _case(
            "portals_duplicate_binding_id_facade_validator",
            "portals.duplicate_binding_id",
            _portal_duplicate_binding_id_facade_validator,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="append an already compiled portal binding",
            changed_fields=("bindings",),
            expected_path_fragment="facilities",
            description="facade validator rejects duplicate compiled binding IDs",
            allowed_codes=("portals.missing",),
        ),
        _case(
            "portals_duplicate_binding_id_active_configuration",
            "portals.duplicate_binding_id",
            _portal_duplicate_binding_id_configuration,
            _portal_configuration_control,
            layer="component",
            validator="facility_portal_route_validation.validate_portal_binding_configuration",
            mutation="activate the same portal binding twice",
            changed_fields=("active_bindings",),
            expected_path_fragment="facilities",
            description="active configuration independently rejects duplicate IDs",
        ),
        _case(
            "portals_missing_id_bijection",
            "portals.missing",
            _portal_missing_id,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="remove exactly one compiled binding",
            changed_fields=("bindings",),
            expected_path_fragment="facilities",
            description="facility and binding ID multisets no longer match",
        ),
        _case(
            "portals_missing_duplicate_facade_key",
            "portals.missing",
            _portal_missing_duplicate_facade,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="copy one binding facade key onto another binding",
            changed_fields=("facade_key",),
            expected_path_fragment="facilities",
            description="one-to-one IDs are insufficient when facade keys collide",
            allowed_codes=("portals.binding_identity_mismatch",),
        ),
        _case(
            "portals_missing_strict_queue_binding",
            "portals.missing",
            _portal_missing_strict_binding,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="mark one otherwise valid binding as fallback-derived",
            changed_fields=("fallback_used",),
            expected_path_fragment="facilities.",
            description="strict compiler refuses fallback portal/queue bindings",
        ),
        _case(
            "portals_missing_compiler_fault",
            "portals.missing",
            _portal_compilation_failed,
            _compiled_control,
            layer="fault_injection",
            validator="validation.validate_compiled_station_design",
            mutation="inject facility portal compiler failure",
            changed_fields=("compile_facility_portal_bindings",),
            expected_path_fragment="facilities",
            description="portal compiler exception is converted into its fallback diagnostic",
        ),
        _case(
            "portals_binding_identity_mismatch_facade_key",
            "portals.binding_identity_mismatch",
            _portal_binding_identity_mismatch,
            portal,
            layer="component",
            validator="facility_portal_validation._binding_identity_issues",
            mutation="replace only the compiled facade key",
            changed_fields=("facade_key",),
            expected_path_fragment="facilities.",
            description="binding no longer represents its source facility facade",
        ),
        _case(
            "portals_outside_walkable_projection_distance",
            "portals.outside_walkable_area",
            _portal_projection_outside,
            portal,
            layer="component",
            validator="facility_portal_validation.validate_facility_portals",
            mutation="raise projection distance beyond the contract tolerance",
            changed_fields=("projection_distance_m",),
            expected_path_fragment="facilities.",
            description="compiler projection required an unsafe correction",
        ),
        _case(
            "portals_outside_walkable_entry_point",
            "portals.outside_walkable_area",
            _portal_entry_outside,
            _point_control,
            layer="component",
            validator="facility_portal_validation._point_issues",
            mutation="move only the raw entry point outside every level domain",
            changed_fields=("raw_entry_point",),
            expected_path_fragment="facilities.",
            description="entry-side point emitter is exercised independently",
        ),
        _case(
            "portals_outside_walkable_exit_point",
            "portals.outside_walkable_area",
            _portal_exit_outside,
            _point_control,
            layer="component",
            validator="facility_portal_validation._point_issues",
            mutation="move only the exit point outside every level domain",
            changed_fields=("exit_point",),
            expected_path_fragment="facilities.",
            description="exit-side point emitter is exercised independently",
        ),
        _case(
            "portals_clearance_too_small_boundary_epsilon",
            "portals.clearance_too_small",
            _portal_clearance_too_small,
            _point_control,
            layer="component",
            validator="facility_portal_validation._point_issues",
            mutation="move portal to half an agent radius from the raw boundary",
            changed_fields=("raw_entry_point", "entry_point", "approach_point"),
            expected_path_fragment="facilities.",
            description="boundary clearance falls below the physical body radius",
            allowed_codes=("portals.outside_walkable_area",),
        ),
        _case(
            "portals_level_mismatch_absent_domain",
            "portals.level_mismatch",
            _portal_level_absent,
            _level_control,
            layer="component",
            validator="facility_portal_validation._level_issues",
            mutation="replace entry level with an absent domain ID",
            changed_fields=("entry_level_id",),
            expected_path_fragment="facilities.",
            description="portal references a level absent from compiled domains",
        ),
        _case(
            "portals_level_mismatch_element_contract",
            "portals.level_mismatch",
            _portal_level_not_declared,
            _level_control,
            layer="component",
            validator="facility_portal_validation._level_issues",
            mutation="move a gate portal to another existing level",
            changed_fields=("entry_level_id",),
            expected_path_fragment="facilities.",
            description="existing level is not declared by the source element",
        ),
        _case(
            "portals_same_side_vertical_facility",
            "portals.same_side",
            _portal_same_side,
            _level_control,
            layer="component",
            validator="facility_portal_validation._level_issues",
            mutation="set vertical exit level equal to its entry level",
            changed_fields=("exit_level_id",),
            expected_path_fragment="facilities.",
            description="vertical connector resolves both facades to one side",
        ),
        _case(
            "portals_facade_mismatch_gate_same_edge",
            "portals.facade_mismatch",
            _portal_facade_mismatch,
            _gate_facade_control,
            layer="component",
            validator="facility_portal_validation._gate_facade_issues",
            mutation="place gate exit on its entry point",
            changed_fields=("exit_point",),
            expected_path_fragment="facilities.",
            description="gate portals no longer lie on opposite transformed edges",
        ),
        _case(
            "portals_variant_group_invalid_group_id",
            "portals.variant_group_invalid",
            _portal_variant_group_invalid,
            _portal_variant_control,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="set activation group inconsistent with facility ID",
            changed_fields=("activation_group_id", "activation_variant_id"),
            expected_path_fragment="facilities.",
            description="activation group and direction variant are inconsistent",
        ),
        _case(
            "queues_topology_missing_version",
            "queues.topology_missing",
            _queue_topology_structural,
            internal,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="bump queue topology version without recompiling",
            changed_fields=("queue_topology_version",),
            expected_path_fragment="facilities.",
            description="structural topology emitter rejects an unsupported version",
        ),
        _case(
            "queues_topology_missing_role_contract",
            "queues.topology_missing",
            _queue_topology_role,
            internal,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="replace one service portal role and recompute its fingerprint",
            changed_fields=("queue_slot_bindings.role", "topology_fingerprint"),
            expected_path_fragment="facilities.",
            description="role emitter is isolated from fingerprint validation",
        ),
        _case(
            "queues_slot_projection_mismatch_approach_tail",
            "queues.slot_projection_mismatch",
            _queue_projection_mismatch,
            internal,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="point approach anchor at the first rather than last waiting slot",
            changed_fields=("approach_point",),
            expected_path_fragment="facilities.",
            description="legacy approach fields disagree with compiled slot topology",
        ),
        _case(
            "queues_service_rank_invalid_gap",
            "queues.service_rank_invalid",
            _queue_service_rank_invalid,
            internal,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="create one service-rank gap and refresh the fingerprint",
            changed_fields=("queue_slot_bindings.service_rank", "topology_fingerprint"),
            expected_path_fragment="facilities.",
            description="occupiable service ranks are no longer dense from zero",
        ),
        _case(
            "queues_row_order_invalid_gap",
            "queues.row_order_invalid",
            _queue_row_order_invalid,
            internal,
            layer="component",
            validator="facility_portal_validation._binding_internal_issues",
            mutation="create one row-index gap and refresh the fingerprint",
            changed_fields=("queue_slot_bindings.row_index", "topology_fingerprint"),
            expected_path_fragment="facilities.",
            description="queue rows are no longer dense and ordered",
        ),
        _case(
            "queues_slot_outside_region_remote_polygon",
            "queues.slot_outside_region",
            _queue_slot_outside_region,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="replace queue region with a remote polygon",
            changed_fields=("queue_region",),
            expected_path_fragment="facilities.",
            description="compiled approach slots fall outside their declared region",
        ),
        _case(
            "queues_slot_clearance_conflict_adjacent",
            "queues.slot_clearance_conflict",
            _queue_adjacent_clearance_conflict,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="place adjacent FIFO slots at half the two-body clearance",
            changed_fields=("queue_slots", "approach_slots"),
            expected_path_fragment="facilities.",
            description="adjacent-slot clearance emitter is exercised independently",
        ),
        _case(
            "queues_slot_clearance_conflict_nonadjacent_edges",
            "queues.slot_clearance_conflict",
            _queue_nonadjacent_clearance_conflict,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="fold nonadjacent FIFO edges within body clearance without crossing",
            changed_fields=("queue_slots", "approach_slots", "entry_point"),
            expected_path_fragment="facilities.",
            description="nonadjacent-edge clearance emitter is exercised independently",
        ),
        _case(
            "queues_slot_clearance_conflict_cross_binding",
            "queues.slot_clearance_conflict",
            _queue_cross_binding_clearance_conflict,
            _queue_cross_binding_control,
            layer="component",
            validator="facility_portal_route_validation.cross_binding_slot_issues",
            mutation="move one co-active binding within another binding's clearance disk",
            changed_fields=("approach_slots",),
            expected_path_fragment="queues.",
            description="dynamic cross-binding emitter reports body-clearance conflict",
        ),
        _case(
            "queues_rank_edge_not_traversable_far_slot",
            "queues.rank_edge_not_traversable",
            _queue_rank_edge_not_traversable,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="move first waiting slot five metres from the portal",
            changed_fields=("queue_slots", "approach_slots"),
            expected_path_fragment="facilities.",
            description="queue rank edge exceeds maximum compiled spacing",
        ),
        _case(
            "queues_slot_detached_duplicate_physical_slot",
            "queues.slot_detached_from_entry",
            _queue_slot_detached,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="duplicate one physical queue slot while preserving FIFO approaches",
            changed_fields=("queue_slots",),
            expected_path_fragment="facilities.",
            description="queue contains duplicate physical standing places",
        ),
        _case(
            "queues_path_self_intersection_bow_tie",
            "queues.path_self_intersection",
            _queue_path_self_intersection,
            route,
            layer="component",
            validator="facility_portal_route_validation.queue_route_issues",
            mutation="replace FIFO path by a body-spaced bow-tie sequence",
            changed_fields=("queue_slots", "approach_slots", "entry_point"),
            expected_path_fragment="facilities.",
            description="compiled FIFO queue line self-intersects",
        ),
        _case(
            "queues_slot_outside_safe_core_remote_slot",
            "queues.slot_outside_safe_core",
            _queue_slot_outside_safe_core,
            _point_control,
            layer="component",
            validator="facility_portal_validation._point_issues",
            mutation="move one physical queue slot outside every level domain",
            changed_fields=("queue_slots",),
            expected_path_fragment="facilities.",
            description="queue standing place is outside the body-safe entry core",
        ),
        _case(
            "queues_slot_overlap_cross_binding",
            "queues.slot_overlap",
            _queue_slot_overlap,
            _queue_cross_binding_control,
            layer="component",
            validator="facility_portal_route_validation.cross_binding_slot_issues",
            mutation="make two co-active facade queues claim the same point",
            changed_fields=("approach_slots",),
            expected_path_fragment="queues.",
            description="dynamic cross-binding emitter reports an exact slot overlap",
        ),
        _case(
            "queues_capacity_not_materialized_declared_plus_one",
            "queues.capacity_not_materialized",
            _queue_capacity_not_materialized,
            _capacity_control,
            layer="component",
            validator="facility_portal_route_validation.capacity_materialization_issues",
            mutation="increase declared source capacity one above materialized slots",
            changed_fields=("source_queue_capacity",),
            expected_path_fragment="queues.",
            description="declared queue capacity is not backed by compiled slots",
        ),
    )


def validate_negative_case(case: CompilationNegativeCase) -> tuple[ValidationIssue, ...]:
    return tuple(case.exercise())


def validate_control_case(case: CompilationNegativeCase) -> tuple[ValidationIssue, ...]:
    return tuple(case.control())


__all__ = [
    "CompilationNegativeCase",
    "ProbeLayer",
    "compilation_negative_cases",
    "validate_control_case",
    "validate_negative_case",
]
