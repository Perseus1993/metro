from __future__ import annotations

from typing import Any

from metro_station.application.semantic_fingerprints import semantic_fingerprint
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.station.graph import StationGraph


def canonical_design_projection(document: StationDesignDocument) -> dict[str, Any]:
    presentation_ids = {
        element.id for element in document.elements if element.metadata.get("presentation_only")
    }
    return {
        "levels": sorted((level.id, level.order, level.elevation_m) for level in document.levels),
        "elements": sorted(
            (
                element.id,
                element.kind,
                element.level_id,
                element.role,
                tuple(sorted(element.connects_levels)),
                element.gate_direction,
                element.direction,
                element.line_id,
            )
            for element in document.elements
            if element.id not in presentation_ids
        ),
        "queues": sorted(
            (queue.id, queue.owner_element_id, queue.level_id, queue.capacity)
            for queue in document.queues
            if queue.owner_element_id not in presentation_ids
        ),
        "connections": sorted(
            (
                connection.id,
                connection.source_id,
                connection.target_id,
                connection.kind,
                connection.bidirectional,
                connection.source_port_id,
                connection.target_port_id,
            )
            for connection in document.connections
            if connection.source_id not in presentation_ids
            and connection.target_id not in presentation_ids
        ),
    }


def canonical_topology_projection(graph: StationGraph) -> dict[str, Any]:
    return {
        "nodes": sorted(
            (
                node.node_id,
                node.level_id,
                node.kind,
                node.element_id,
                node.line_id,
                node.direction,
                node.facility_stage,
            )
            for node in graph.nodes.values()
        ),
        "edges": sorted(
            (
                edge.from_node,
                edge.to_node,
                edge.kind,
                edge.level_change,
                edge.bidirectional,
                edge.facility_stage,
                edge.origin,
                edge.detail_id,
            )
            for edge in graph.edges
        ),
        "diagnostics": sorted(
            (item.severity, item.code, item.connection_id, item.element_id)
            for item in graph.compile_diagnostics
        ),
    }


def canonical_fingerprint(projection: dict[str, Any]) -> str:
    return semantic_fingerprint(projection)
