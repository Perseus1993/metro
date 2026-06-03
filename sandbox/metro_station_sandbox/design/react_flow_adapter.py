from __future__ import annotations

from dataclasses import replace
from typing import Any

from .schema import (
    DesignConnection,
    DesignElement,
    DesignPort,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)
from .templates import _with_standard_ports


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


def apply_react_flow_nodes(
    document: StationDesignDocument,
    nodes: list[dict[str, Any]],
) -> StationDesignDocument:
    """Apply React Flow node edits and create inspector-dropped draft elements.

    Existing template elements remain authoritative. React Flow can move existing movable
    elements and append explicit inspector draft nodes; it cannot silently delete built-in
    domain elements by omitting them from the UI payload.
    """

    document = apply_react_flow_positions(document, nodes)
    known_element_ids = {element.id for element in document.elements}
    draft_elements: list[DesignElement] = []
    for node in nodes:
        draft_element = _draft_element_from_node(document, node, known_element_ids)
        if draft_element is None:
            continue
        draft_elements.append(draft_element)
        known_element_ids.add(draft_element.id)
    if not draft_elements:
        return document
    return replace(document, elements=(*document.elements, *draft_elements))


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
                source_port_id=edge.get("sourceHandle"),
                target_port_id=edge.get("targetHandle"),
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
            "level_id": element.level_id,
            "role": element.role,
            "label": element.label,
            "connects_levels": list(element.connects_levels),
            "capacity": element.capacity,
            "queue_policy": element.queue_policy,
            "ports": [port.as_dict() for port in element.ports],
            "geometry": element.geometry.as_dict(),
            "gate_direction": element.gate_direction,
            "direction": element.direction,
            "line_id": element.line_id,
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
            "level_id": queue.level_id,
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
        "sourceHandle": connection.source_port_id,
        "targetHandle": connection.target_port_id,
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


def _draft_element_from_node(
    document: StationDesignDocument,
    node: dict[str, Any],
    known_element_ids: set[str],
) -> DesignElement | None:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if not data.get("inspector_created"):
        return None

    element_id = _unprefix(str(node.get("id", "")), ("element:",))
    if not element_id or element_id in known_element_ids:
        return None

    kind = str(data.get("kind") or "")
    if kind != "platform_edge" and kind not in set(document.constraints.allowed_facility_kinds):
        return None

    level_id = _draft_level_id(document, node, data)
    geometry = _draft_geometry(node, data)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    ports = tuple(
        DesignPort.from_dict(port)
        for port in data.get("ports", ())
        if isinstance(port, dict)
    )
    element = DesignElement(
        id=element_id,
        kind=kind,
        level_id=level_id,
        geometry=geometry,
        label=str(data.get("label") or element_id),
        role=str(data.get("role") or "facility"),
        movable=True,
        resizable=bool(data.get("resizable", True)),
        connects_levels=tuple(data.get("connects_levels") or ()),
        capacity=_optional_positive_int(data.get("capacity")),
        queue_policy=data.get("queue_policy") if isinstance(data.get("queue_policy"), dict) else {},
        ports=ports,
        metadata={**metadata, "inspector_created": True},
        gate_direction=data.get("gate_direction"),
        direction=data.get("direction"),
        line_id=data.get("line_id"),
    )
    return _with_standard_ports(element)


def _draft_level_id(
    document: StationDesignDocument,
    node: dict[str, Any],
    data: dict[str, Any],
) -> str:
    level_id = data.get("level_id")
    if level_id:
        return str(level_id)
    parent_id = str(node.get("parentId") or "")
    if parent_id.startswith("level:"):
        return parent_id.removeprefix("level:")
    return document.levels[0].id


def _draft_geometry(node: dict[str, Any], data: dict[str, Any]) -> ElementGeometry:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    raw_geometry = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    width = _number(node.get("width"), _number(style.get("width"), raw_geometry.get("width_m", 4.0)))
    height = _number(
        node.get("height"),
        _number(style.get("height"), raw_geometry.get("height_m", 3.0)),
    )
    return ElementGeometry(
        shape=str(raw_geometry.get("shape") or "rect"),
        x_m=_number(position.get("x"), raw_geometry.get("x_m", 0.0)),
        y_m=_number(position.get("y"), raw_geometry.get("y_m", 0.0)),
        width_m=max(width, 0.5),
        height_m=max(height, 0.5),
        rotation_deg=_number(raw_geometry.get("rotation_deg"), 0.0),
        points_m=tuple(tuple(point) for point in raw_geometry.get("points_m", ())),
    )


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


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
