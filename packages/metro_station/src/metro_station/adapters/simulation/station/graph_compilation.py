from __future__ import annotations

from math import hypot
from typing import Any

from shapely.geometry import LineString

from ..planning.plan import FacilityStage
from ..design.helpers import (
    gate_direction as _gate_direction,
    vertical_direction as _vertical_direction,
)
from ..design.schema import (
    DesignConnection,
    DesignElement,
    DesignPort,
    QueueSpec,
    StationDesignDocument,
)
from ..design.vertical_landing import (
    DEFAULT_VERTICAL_LANDING_CLEARANCE_M,
    vertical_landing_position,
)
from .geometry import (
    element_representative_point,
    element_walkable_domain,
    level_walkable_geometry,
    project_to_safe_point,
)
from .graph_types import GraphCompileDiagnostic, GraphEdge, GraphNode, Point


def _queues_by_owner(queues: tuple[QueueSpec, ...]) -> dict[str, tuple[QueueSpec, ...]]:
    grouped: dict[str, list[QueueSpec]] = {}
    for queue in queues:
        grouped.setdefault(queue.owner_element_id, []).append(queue)
    return {owner_id: tuple(items) for owner_id, items in grouped.items()}


def _distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _add_edge(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    from_node: str,
    to_node: str,
    *,
    kind: str,
    bidirectional: bool = False,
    facility_stage: str | None = None,
    origin: str,
    detail_id: str | None = None,
) -> None:
    source = nodes[from_node]
    target = nodes[to_node]
    cost = _distance(source.position, target.position)
    level_change = source.level_id != target.level_id
    edges.append(
        GraphEdge(
            from_node,
            to_node,
            kind,
            cost,
            level_change,
            bidirectional,
            facility_stage,
            origin,
            detail_id,
        )
    )
    if bidirectional:
        edges.append(
            GraphEdge(
                to_node,
                from_node,
                kind,
                cost,
                level_change,
                bidirectional,
                facility_stage,
                origin,
                detail_id,
            )
        )


def _add_gate_service_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    element: DesignElement,
) -> None:
    direction = _gate_direction(element)
    if direction in {"entry", "bidirectional"}:
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:entry",
            f"gate:{element.id}:paid",
            kind="service",
            facility_stage=FacilityStage.ENTRY_GATE.value,
            origin="facility_service",
            detail_id=element.id,
        )
    if direction in {"exit", "bidirectional"}:
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:exit",
            f"gate:{element.id}:unpaid",
            kind="service",
            facility_stage=FacilityStage.EXIT_GATE.value,
            origin="facility_service",
            detail_id=element.id,
        )
    if direction == "bidirectional":
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:unpaid",
            f"gate:{element.id}:entry",
            kind="walk",
            bidirectional=True,
            origin="facility_internal",
            detail_id=element.id,
        )
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:paid",
            f"gate:{element.id}:exit",
            kind="walk",
            bidirectional=True,
            origin="facility_internal",
            detail_id=element.id,
        )


def _add_vertical_service_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    element: DesignElement,
    levels_by_id: dict[str, Any],
) -> None:
    ordered_levels = sorted(
        element.connects_levels,
        key=lambda level_id: levels_by_id[level_id].elevation_m,
        reverse=True,
    )
    direction = _vertical_direction(element)
    for upper, lower in zip(ordered_levels, ordered_levels[1:]):
        upper_node = f"vertical:{element.id}:{upper}"
        lower_node = f"vertical:{element.id}:{lower}"
        if direction in {"down", "both"}:
            _add_edge(
                edges,
                nodes,
                upper_node,
                lower_node,
                kind="vertical",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                origin="facility_service",
                detail_id=element.id,
            )
        if direction in {"up", "both"}:
            _add_edge(
                edges,
                nodes,
                lower_node,
                upper_node,
                kind="vertical",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                origin="facility_service",
                detail_id=element.id,
            )


def _add_same_level_walkable_access_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    document: StationDesignDocument,
    walkable_geometry,
    diagnostics: list[GraphCompileDiagnostic],
) -> None:
    """Connect physical access points to their same-level walkable floor.

    Explicit design connections still define the station process graph. This
    pass prevents valid physical endpoints, especially vertical-connector ends,
    from becoming graph islands when they are already inside the same walkable
    floor component.
    """

    edge_pairs = {(edge.from_node, edge.to_node) for edge in edges if edge.kind == "walk"}

    def add_walk_edge(from_node: str, to_node: str) -> None:
        if from_node == to_node or (from_node, to_node) in edge_pairs:
            return
        _add_edge(
            edges,
            nodes,
            from_node,
            to_node,
            kind="walk",
            bidirectional=True,
            origin="walkable_access_fallback",
        )
        edge_pairs.add((from_node, to_node))
        edge_pairs.add((to_node, from_node))
        source = nodes[from_node]
        target = nodes[to_node]
        diagnostics.append(
            GraphCompileDiagnostic(
                "warning",
                "graph.same_level_access_fallback",
                f"implicit same-level walkable access edge added: {from_node}->{to_node}",
                element_id=source.element_id or target.element_id,
                from_node=from_node,
                to_node=to_node,
                metadata={
                    "source_element_id": source.element_id,
                    "target_element_id": target.element_id,
                    "level_id": source.level_id,
                },
            )
        )

    for level in document.levels:
        level_nodes = [node for node in nodes.values() if node.level_id == level.id]
        zone_nodes = [node for node in level_nodes if node.kind == "zone"]
        if not zone_nodes:
            continue

        level_domain = level_walkable_geometry(document, level.id, walkable_geometry)
        for node in level_nodes:
            if not _needs_same_level_floor_access(node):
                continue
            if _has_same_level_zone_access(node, zone_nodes, edge_pairs):
                continue
            candidates = [
                zone
                for zone in zone_nodes
                if _same_level_walk_segment_supported(level_domain, node.position, zone.position)
            ]
            if not candidates:
                candidates = zone_nodes
            nearest = min(candidates, key=lambda zone: _distance(node.position, zone.position))
            add_walk_edge(node.node_id, nearest.node_id)

        for left in zone_nodes:
            if _has_same_level_zone_access(left, zone_nodes, edge_pairs):
                continue
            candidates = [
                right
                for right in zone_nodes
                if right.node_id != left.node_id
                and _same_level_walk_segment_supported(level_domain, left.position, right.position)
            ]
            if candidates:
                nearest = min(
                    candidates, key=lambda right: _distance(left.position, right.position)
                )
                add_walk_edge(left.node_id, nearest.node_id)


def _needs_same_level_floor_access(node: GraphNode) -> bool:
    if node.kind in {"entrance", "platform"}:
        return True
    if node.kind == "facility_exit":
        return True
    return (
        node.kind in {"facility_entry", "facility_exit"}
        and node.facility_stage == FacilityStage.VERTICAL_TRANSFER.value
    )


def _has_same_level_zone_access(
    node: GraphNode,
    zone_nodes: list[GraphNode],
    edge_pairs: set[tuple[str, str]],
) -> bool:
    return any(
        (node.node_id, zone.node_id) in edge_pairs or (zone.node_id, node.node_id) in edge_pairs
        for zone in zone_nodes
    )


def _same_level_walk_segment_supported(level_domain, start: Point, end: Point) -> bool:
    if level_domain.is_empty:
        return False
    segment = LineString((start, end))
    if segment.length <= 0.001:
        return True
    return level_domain.buffer(0.05).covers(segment)


def _connection_node_id_for_connection(
    connection: DesignConnection,
    element: DesignElement,
    other: DesignElement,
    endpoint: str,
    primary_node_by_element_id: dict[str, str],
    diagnostics: list[GraphCompileDiagnostic],
) -> str:
    port_id = connection.source_port_id if endpoint == "source" else connection.target_port_id
    if port_id is None:
        diagnostics.append(
            GraphCompileDiagnostic(
                "info",
                "graph.connection_endpoint_inferred",
                f"{connection.id} {endpoint} endpoint uses legacy element-to-node inference",
                connection_id=connection.id,
                element_id=element.id,
                metadata={"endpoint": endpoint},
            )
        )
        return _connection_node_id(element, other, primary_node_by_element_id)

    port_node_id = _connection_node_id_for_port(element, port_id, primary_node_by_element_id)
    if port_node_id is not None:
        return port_node_id

    diagnostics.append(
        GraphCompileDiagnostic(
            "warning",
            "graph.port_endpoint_fallback",
            f"{connection.id} {endpoint} port {element.id}.{port_id} "
            "could not be mapped to a graph node; legacy inference was used",
            connection_id=connection.id,
            element_id=element.id,
            metadata={"endpoint": endpoint, "port_id": port_id},
        )
    )
    return _connection_node_id(element, other, primary_node_by_element_id)


def _connection_node_id_for_port(
    element: DesignElement,
    port_id: str,
    primary_node_by_element_id: dict[str, str],
) -> str | None:
    port = _design_port_by_id(element).get(port_id)
    if port is None:
        return None

    graph_node_id = port.metadata.get("graph_node_id")
    if isinstance(graph_node_id, str) and graph_node_id:
        return graph_node_id

    if element.role == "vertical_connector":
        level_id = port.level_id or element.level_id
        if level_id in element.connects_levels:
            return f"vertical:{element.id}:{level_id}"
        return None

    if element.kind == "gate":
        return _gate_connection_node_id_for_port(element, port)

    return primary_node_by_element_id.get(element.id)


def _gate_connection_node_id_for_port(element: DesignElement, port: DesignPort) -> str | None:
    direction = _gate_direction(element)
    if port.kind == "service":
        if direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:entry"
        if direction == "exit":
            return f"gate:{element.id}:exit"
    if port.kind == "release":
        if direction == "exit":
            return f"gate:{element.id}:unpaid"
        if direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:paid"
    if port.kind == "fare_unpaid":
        if port.direction == "out" and direction in {"exit", "bidirectional"}:
            return f"gate:{element.id}:unpaid"
        if direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:entry"
        if direction == "exit":
            return f"gate:{element.id}:unpaid"
    if port.kind == "fare_paid":
        if port.direction == "out" and direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:paid"
        if direction in {"exit", "bidirectional"}:
            return f"gate:{element.id}:exit"
        if direction == "entry":
            return f"gate:{element.id}:paid"
    return _primary_gate_node_id(element)


def _primary_gate_node_id(element: DesignElement) -> str | None:
    direction = _gate_direction(element)
    if direction in {"entry", "bidirectional"}:
        return f"gate:{element.id}:paid"
    if direction == "exit":
        return f"gate:{element.id}:exit"
    return None


def _design_port_by_id(element: DesignElement) -> dict[str, DesignPort]:
    return {port.id: port for port in element.ports}


def _connection_node_id(
    element: DesignElement,
    other: DesignElement,
    primary_node_by_element_id: dict[str, str],
) -> str:
    if element.kind == "gate":
        direction = _gate_direction(element)
        if other.kind == "entrance" and direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:entry"
        if direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:paid"
        if direction == "exit":
            return f"gate:{element.id}:exit"
    if element.role == "vertical_connector":
        if other.level_id in element.connects_levels:
            return f"vertical:{element.id}:{other.level_id}"
    return primary_node_by_element_id[element.id]


def _vertical_node_position(
    element: DesignElement,
    level_id: str,
    levels_by_id: dict[str, Any],
    document: StationDesignDocument,
    walkable_geometry,
) -> Point:
    level_area = level_walkable_geometry(document, level_id, walkable_geometry)
    return vertical_landing_position(
        element,
        level_id,
        levels_by_id,
        walkable_geometry=level_area,
        clearance=DEFAULT_VERTICAL_LANDING_CLEARANCE_M,
    )


def _element_node_position(element: DesignElement, walkable_geometry) -> Point:
    domain = element_walkable_domain(element, walkable_geometry)
    raw = element_representative_point(element.geometry)
    return project_to_safe_point(domain, raw, clearance=0.18, require_inside=False)


def _dedupe_positions(points: tuple[Point, ...]) -> list[Point]:
    deduped: list[Point] = []
    for point in points:
        if not deduped or _distance(deduped[-1], point) > 0.001:
            deduped.append(point)
    return deduped
