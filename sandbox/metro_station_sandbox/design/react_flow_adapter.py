from __future__ import annotations

from dataclasses import replace
from typing import Any

from .schema import (
    DesignConnection,
    DesignElement,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)


LEVEL_GAP_Y = 130.0


def to_react_flow(document: StationDesignDocument) -> dict[str, Any]:
    """Project the design document into React Flow nodes/edges for a future editor."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    level_offsets = _level_offsets(document)

    for level in sorted(document.levels, key=lambda item: item.order):
        offset_y = level_offsets[level.id]
        nodes.append(
            {
                "id": f"level:{level.id}",
                "type": "levelGroup",
                "position": {"x": 0, "y": offset_y},
                "data": {
                    "level_id": level.id,
                    "label": level.label,
                    "elevation_m": level.elevation_m,
                    "floor_to_floor_height_m": level.floor_to_floor_height_m,
                },
                "style": {
                    "width": document.constraints.canvas_width_m,
                    "height": document.constraints.canvas_height_m,
                },
                "draggable": False,
                "selectable": True,
                "zIndex": -10,
            }
        )

    for element in document.elements:
        nodes.append(_element_node(element))

    for queue in document.queues:
        nodes.append(_queue_node(queue))

    for connection in document.connections:
        edges.append(_connection_edge(connection))

    return {
        "schema_version": "react-flow-projection/v1",
        "source_schema_version": document.schema_version,
        "document_id": document.id,
        "coordinate_system": "meters",
        "editor_pattern": "document_model_with_editor_adapter",
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 24, "y": 24, "zoom": 6.0},
        "nodeTypes": [
            "levelGroup",
            "floorZone",
            "facilityNode",
            "verticalConnector",
            "queueLane",
            "queueGrid",
        ],
        "metadata": {
            "recommended_library": "@xyflow/react",
            "reference_repo": "https://github.com/xyflow/xyflow",
            "update_rule": "React Flow edits are projected back onto StationDesignDocument geometry; simulation never reads React Flow state directly.",
        },
    }


def apply_react_flow_positions(
    document: StationDesignDocument,
    nodes: list[dict[str, Any]],
) -> StationDesignDocument:
    """Apply node position changes back to the design document.

    This intentionally ignores styling and runtime UI fields. The design document remains the
    source of truth, and the editor is only allowed to mutate business geometry here.
    """

    node_positions = {
        node.get("id"): node.get("position", {})
        for node in nodes
        if isinstance(node.get("position"), dict)
    }
    elements = tuple(
        _apply_element_position(element, node_positions) for element in document.elements
    )
    queues = tuple(_apply_queue_position(queue, node_positions) for queue in document.queues)
    return replace(document, elements=elements, queues=queues)


def apply_react_flow_edges(
    document: StationDesignDocument,
    edges: list[dict[str, Any]],
) -> StationDesignDocument:
    connections: list[DesignConnection] = []
    for edge in edges:
        source = _unprefix(edge.get("source", ""), ("element:", "queue:"))
        target = _unprefix(edge.get("target", ""), ("element:", "queue:"))
        if not source or not target:
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        connections.append(
            DesignConnection(
                id=_unprefix(edge.get("id", f"edge:{source}:{target}"), ("edge:",)),
                source_id=source,
                target_id=target,
                kind=data.get("kind", "walk"),
                bidirectional=data.get("bidirectional", True),
                metadata=data.get("metadata", {}),
            )
        )
    return replace(document, connections=tuple(connections))


def _element_node(element: DesignElement) -> dict[str, Any]:
    x_m, y_m, width_m, height_m = _node_bounds(element.geometry)
    node_type = "floorZone" if element.role == "floor" else "facilityNode"
    if element.role == "vertical_connector":
        node_type = "verticalConnector"
    return {
        "id": f"element:{element.id}",
        "type": node_type,
        "parentId": f"level:{element.level_id}",
        "extent": "parent",
        "position": {"x": x_m, "y": y_m},
        "width": width_m,
        "height": height_m,
        "data": {
            "element_id": element.id,
            "kind": element.kind,
            "role": element.role,
            "label": element.label,
            "connects_levels": list(element.connects_levels),
            "capacity": element.capacity,
            "queue_policy": element.queue_policy,
            "geometry": element.geometry.as_dict(),
        },
        "draggable": element.movable,
        "selectable": True,
        "resizing": {"enabled": element.resizable},
    }


def _queue_node(queue: QueueSpec) -> dict[str, Any]:
    x_m, y_m, width_m, height_m = _node_bounds(queue.geometry)
    return {
        "id": f"queue:{queue.id}",
        "type": "queueGrid" if queue.kind == "grid" else "queueLane",
        "parentId": f"level:{queue.level_id}",
        "extent": "parent",
        "position": {"x": x_m, "y": y_m},
        "width": width_m,
        "height": height_m,
        "data": {
            "queue_id": queue.id,
            "owner_element_id": queue.owner_element_id,
            "kind": queue.kind,
            "label": queue.label,
            "capacity": queue.capacity,
            "spacing_m": queue.spacing_m,
            "direction_deg": queue.direction_deg,
            "service_point_m": list(queue.service_point_m),
            "geometry": queue.geometry.as_dict(),
        },
        "draggable": True,
        "selectable": True,
        "resizing": {"enabled": True},
    }


def _connection_edge(connection: DesignConnection) -> dict[str, Any]:
    return {
        "id": f"edge:{connection.id}",
        "source": f"element:{connection.source_id}",
        "target": f"element:{connection.target_id}",
        "type": "smoothstep",
        "data": {
            "kind": connection.kind,
            "bidirectional": connection.bidirectional,
            "metadata": connection.metadata,
        },
        "animated": connection.kind == "vertical",
    }


def _node_bounds(geometry: ElementGeometry) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = geometry.bounds()
    width = max(geometry.width_m, max_x - min_x, 1.0)
    height = max(geometry.height_m, max_y - min_y, 1.0)
    return min_x, min_y, width, height


def _apply_element_position(
    element: DesignElement,
    positions: dict[str, dict[str, Any]],
) -> DesignElement:
    position = positions.get(f"element:{element.id}")
    if not position or not element.movable:
        return element
    geometry = element.geometry.moved_to(
        float(position.get("x", 0.0)), float(position.get("y", 0.0))
    )
    return replace(element, geometry=geometry)


def _apply_queue_position(
    queue: QueueSpec,
    positions: dict[str, dict[str, Any]],
) -> QueueSpec:
    position = positions.get(f"queue:{queue.id}")
    if not position:
        return queue
    geometry = queue.geometry.moved_to(float(position.get("x", 0.0)), float(position.get("y", 0.0)))
    return replace(queue, geometry=geometry)


def _level_offsets(document: StationDesignDocument) -> dict[str, float]:
    return {
        level.id: level.order * (document.constraints.canvas_height_m + LEVEL_GAP_Y)
        for level in document.levels
    }


def _unprefix(value: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value
