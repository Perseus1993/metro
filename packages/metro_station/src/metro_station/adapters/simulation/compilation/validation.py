from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..design.schema import StationDesignDocument
from ..design.validation import ValidationIssue, validate_design_schema
from ..station.graph import StationGraph
from .geometry_reachability import GeometryCompilePolicy, validate_geometry_reachability


@dataclass(frozen=True)
class CompiledStationValidation:
    """One scenario-aware graph/portal artifact shared by validator and runtime."""

    station_graph: StationGraph | None
    facilities: tuple[Any, ...]
    facility_portal_bindings: tuple[Any, ...]
    facility_portal_binding_variants: tuple[Any, ...]
    decision_holding_regions: tuple[Any, ...]
    spatial_capacity_certificates: tuple[Any, ...]
    spatial_demand_contracts: tuple[Any, ...]
    policy: GeometryCompilePolicy
    issues: tuple[ValidationIssue, ...]


def validate_compiled_station_design(
    document: StationDesignDocument,
    scenario: Any,
) -> CompiledStationValidation:
    from ..station.layout_facilities import _facility_specs_from_station_graph
    from .decision_holding_regions import (
        compile_decision_holding_regions,
        validate_decision_holding_regions,
    )
    from .facility_portals import (
        compile_facility_portal_bindings,
        compile_reversed_escalator_portal_binding,
        validate_facility_portals,
        validate_portal_binding_compatibility,
    )
    from .spatial_capacity import (
        compile_spatial_capacity_certificates,
        compile_spatial_demand_contracts,
        validate_spatial_capacity_certificates,
        validate_spatial_demand_contracts,
    )

    policy = GeometryCompilePolicy.from_scenario(scenario)
    try:
        graph = StationGraph.from_design(
            document,
            include_walkable_access_edges=False,
        )
    except Exception:
        graph = None
    issues = validate_station_design(
        document,
        geometry_policy=policy,
        station_graph=graph,
    )
    if graph is None or any(item.severity == "error" for item in issues):
        return CompiledStationValidation(
            station_graph=graph,
            facilities=(),
            facility_portal_bindings=(),
            facility_portal_binding_variants=(),
            decision_holding_regions=(),
            spatial_capacity_certificates=(),
            spatial_demand_contracts=(),
            policy=policy,
            issues=tuple(issues),
        )
    try:
        facilities = tuple(_facility_specs_from_station_graph(graph, scenario))
        bindings = compile_facility_portal_bindings(
            document,
            facilities,
            policy=policy,
            graph=graph,
        )
        portal_issues = validate_facility_portals(
            document,
            facilities,
            bindings,
            policy=policy,
        )
        variants: list[Any] = []
        control_plan = getattr(scenario, "control_plan", None)
        reversible_ids = {
            str(measure.target_id)
            for measure in (() if control_plan is None else control_plan.measures)
            if measure.kind == "escalator_direction" and measure.target_id is not None
        }
        facility_by_id = {facility.facility_id: facility for facility in facilities}
        binding_by_id = {binding.facility_id: binding for binding in bindings}
        for facility_id in sorted(reversible_ids):
            facility = facility_by_id.get(facility_id)
            binding = binding_by_id.get(facility_id)
            if facility is None or binding is None:
                raise ValueError(
                    f"reversible escalator {facility_id!r} has no compiled base binding"
                )
            reverse_spec, reverse_binding = compile_reversed_escalator_portal_binding(
                document,
                facility,
                binding,
                policy=policy,
            )
            portal_issues.extend(
                validate_facility_portals(
                    document,
                    (reverse_spec,),
                    (reverse_binding,),
                    policy=policy,
                )
            )
            variants.append(reverse_binding)
        portal_issues.extend(
            validate_portal_binding_compatibility(
                (*bindings, *variants),
                policy=policy,
            )
        )
    except Exception as exc:
        portal_issues = [
            _issue(
                "error",
                "portals.missing",
                "facilities",
                f"facility portal compilation failed: {type(exc).__name__}: {exc}",
            )
        ]
        facilities = ()
        bindings = ()
        variants = []
        holding_regions = ()
        capacity_certificates = ()
        demand_contracts = ()
    else:
        try:
            holding_regions = compile_decision_holding_regions(
                document,
                graph,
                (*bindings, *variants),
                policy=policy,
                scenario=scenario,
                facilities=facilities,
            )
            portal_issues.extend(validate_decision_holding_regions(holding_regions))
            capacity_certificates = compile_spatial_capacity_certificates(
                document,
                graph,
                facilities,
                (*bindings, *variants),
                holding_regions,
                scenario=scenario,
                policy=policy,
            )
            portal_issues.extend(
                validate_spatial_capacity_certificates(capacity_certificates)
            )
            demand_contracts = compile_spatial_demand_contracts(
                facilities,
                capacity_certificates,
                scenario=scenario,
            )
            portal_issues.extend(validate_spatial_demand_contracts(demand_contracts))
        except Exception as exc:
            holding_regions = ()
            capacity_certificates = ()
            demand_contracts = ()
            portal_issues.append(
                _issue(
                    "error",
                    "capacity.compile_failed",
                    "facilities",
                    "spatial capacity compilation failed: "
                    f"{type(exc).__name__}: {exc}",
                )
            )
    return CompiledStationValidation(
        station_graph=graph,
        facilities=facilities,
        facility_portal_bindings=bindings,
        facility_portal_binding_variants=tuple(variants),
        decision_holding_regions=tuple(holding_regions),
        spatial_capacity_certificates=tuple(capacity_certificates),
        spatial_demand_contracts=tuple(demand_contracts),
        policy=policy,
        issues=(*issues, *portal_issues),
    )


def validate_station_design(
    document: StationDesignDocument,
    *,
    geometry_policy: GeometryCompilePolicy | None = None,
    station_graph: StationGraph | None = None,
) -> list[ValidationIssue]:
    """Run schema/geometry validation before graph compilation and topology validation."""

    issues = validate_design_schema(document)
    if any(issue.severity == "error" for issue in issues):
        return issues
    topology_issues, graph = _validate_station_topology_with_graph(
        document,
        station_graph=station_graph,
    )
    if graph is None:
        return [*issues, *topology_issues]
    return [
        *issues,
        *topology_issues,
        *validate_geometry_reachability(document, graph=graph, policy=geometry_policy),
    ]


def validate_station_topology(document: StationDesignDocument) -> list[ValidationIssue]:
    issues, _graph = _validate_station_topology_with_graph(document)
    return issues


def _validate_station_topology_with_graph(
    document: StationDesignDocument,
    *,
    station_graph: StationGraph | None = None,
) -> tuple[list[ValidationIssue], StationGraph | None]:
    try:
        graph = station_graph or StationGraph.from_design(
            document,
            include_walkable_access_edges=False,
        )
    except Exception as exc:
        return (
            [
                _issue(
                "error",
                "graph.compile_failed",
                "connections",
                f"station graph could not be compiled: {type(exc).__name__}: {exc}",
                )
            ],
            None,
        )
    return _graph_reachability_issues(graph), graph


def _graph_reachability_issues(graph: StationGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entrance_nodes = graph.nodes_matching(kind="entrance")
    platform_nodes = graph.nodes_matching(kind="platform")
    if not entrance_nodes or not platform_nodes:
        return issues

    reachable = _undirected_reachable(graph, {node.node_id for node in entrance_nodes})
    for node in graph.nodes.values():
        if node.kind not in {"entrance", "zone", "facility_entry", "facility_exit", "platform"}:
            continue
        if node.node_id in reachable:
            continue
        issues.append(
            _issue(
                "error",
                "graph.unreachable_node",
                f"elements.{node.element_id or node.node_id}",
                f"graph node {node.node_id!r} is unreachable from any entrance; "
                "add an explicit DesignConnection",
            )
        )

    platform_targets = {node.node_id for node in platform_nodes}
    for entrance in entrance_nodes:
        if graph.shortest_path(entrance.node_id, platform_targets) is not None:
            continue
        issues.append(
            _issue(
                "error",
                "graph.enter_path_missing",
                f"elements.{entrance.element_id}",
                f"no directed route from entrance node {entrance.node_id!r} to any platform",
            )
        )

    exit_targets = {
        node.node_id
        for node in graph.nodes_matching(kind="facility_entry", facility_stage="exit_gate")
    }
    for platform in platform_nodes:
        if not exit_targets or graph.shortest_path(platform.node_id, exit_targets) is not None:
            continue
        issues.append(
            _issue(
                "error",
                "graph.exit_path_missing",
                f"elements.{platform.element_id}",
                f"no directed exit route from platform node {platform.node_id!r} to any exit gate",
            )
        )
    return issues


def _undirected_reachable(graph: StationGraph, start_nodes: set[str]) -> set[str]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in graph.nodes}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_node, set()).add(edge.to_node)
        adjacency.setdefault(edge.to_node, set()).add(edge.from_node)

    seen: set[str] = set()
    stack = list(start_nodes)
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(adjacency.get(node_id, ()) - seen)
    return seen


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)
