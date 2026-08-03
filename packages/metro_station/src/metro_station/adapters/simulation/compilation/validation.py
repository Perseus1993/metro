from __future__ import annotations

from ..design.schema import StationDesignDocument
from ..design.validation import ValidationIssue, validate_design_schema
from ..station.graph import StationGraph


def validate_station_design(document: StationDesignDocument) -> list[ValidationIssue]:
    """Run schema/geometry validation before graph compilation and topology validation."""

    issues = validate_design_schema(document)
    if any(issue.severity == "error" for issue in issues):
        return issues
    return [*issues, *validate_station_topology(document)]


def validate_station_topology(document: StationDesignDocument) -> list[ValidationIssue]:
    try:
        graph = StationGraph.from_design(document, include_walkable_access_edges=False)
    except Exception as exc:
        return [
            _issue(
                "error",
                "graph.compile_failed",
                "connections",
                f"station graph could not be compiled: {type(exc).__name__}: {exc}",
            )
        ]
    return _graph_reachability_issues(graph)


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
