"""Serialize the compiled station graph into the public routing contract."""

from __future__ import annotations

from metro_station.application.routing_plugins import (
    RoutingEdge,
    RoutingNode,
    RoutingTopology,
)


def station_graph_topology(station_graph) -> RoutingTopology:
    nodes = tuple(
        RoutingNode(
            node.node_id,
            node.level_id,
            float(node.position[0]),
            float(node.position[1]),
            node.kind,
            {
                "element_id": node.element_id,
                "line_id": node.line_id,
                "direction": node.direction,
                "facility_stage": node.facility_stage,
                "tactical_anchor": bool(node.tactical_anchor),
            },
        )
        for node in sorted(station_graph.nodes.values(), key=lambda item: item.node_id)
    )
    edges = tuple(
        RoutingEdge(
            _edge_id(index, edge),
            edge.from_node,
            edge.to_node,
            float(edge.cost),
            edge.kind,
            {
                "facility_stage": edge.facility_stage,
                "origin": edge.origin,
                "detail_id": edge.detail_id,
                "level_change": bool(edge.level_change),
            },
        )
        for index, edge in enumerate(station_graph.edges)
    )
    document = station_graph.source_document
    design_id = "unknown" if document is None else document.id
    return RoutingTopology(f"station-graph:{design_id}", nodes, edges)


def closed_topology_edge_ids(model, topology: RoutingTopology) -> tuple[str, ...]:
    controller = getattr(model, "disruption_controller", None)
    if controller is None:
        return ()
    disabled = set(controller.static_disabled_ids) | set(controller.dynamic_disabled_ids)
    element_ids = {_facility_element_id(facility_id) for facility_id in disabled}
    return tuple(
        edge.edge_id
        for edge in topology.edges
        if edge.kind != "walk" or edge.metadata.get("detail_id") in element_ids
    )


def _edge_id(index: int, edge) -> str:
    return f"edge:{index:05d}:{edge.from_node}->{edge.to_node}:{edge.kind}"


def _facility_element_id(facility_id: str) -> str:
    parts = facility_id.split(":")
    return parts[1] if len(parts) >= 2 else facility_id
