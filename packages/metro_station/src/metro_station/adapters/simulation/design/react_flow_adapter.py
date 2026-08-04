from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any

from .layout_rules import element_size_limits
from .schema import (
    DesignConnection,
    DesignElement,
    DesignPort,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)
from .templates import _with_standard_ports
from .transforms import GeometryTransform, transform_element, transform_ports, translate_queue


LEVEL_GAP_Y = 32.0


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
                    "editor_scratch": bool(document.metadata.get("editor_scratch")),
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
        "viewport": {"x": 0, "y": 0, "zoom": 1.0},
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

    nodes_by_id = {
        str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")
    }
    element_results = tuple(
        _apply_element_transform(element, nodes_by_id) for element in document.elements
    )
    elements = tuple(element for element, _transform in element_results)
    owner_transforms = {
        element.id: transform
        for element, (_updated, transform) in zip(document.elements, element_results, strict=True)
    }
    queues = tuple(
        _apply_queue_transform(queue, nodes_by_id, owner_transforms) for queue in document.queues
    )
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
    limits = element_size_limits(element.kind)
    return {
        "id": f"element:{element.id}",
        "type": node_type,
        "parentId": f"level:{element.level_id}",
        "extent": "parent",
        "position": {"x": x_m, "y": y_m},
        "width": width_m,
        "height": height_m,
        "data": {
            "inspector_created": bool(element.metadata.get("inspector_created")),
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
            "resizable": element.resizable,
            "size_limits_m": limits.as_dict() if limits is not None else None,
            "metadata": dict(element.metadata),
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
            "service_direction": queue.service_direction,
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


def _apply_element_transform(
    element: DesignElement,
    nodes_by_id: dict[str, dict[str, Any]],
) -> tuple[DesignElement, GeometryTransform]:
    node = nodes_by_id.get(f"element:{element.id}")
    old_x, old_y, _, _ = element.geometry.bounds()
    if node is None:
        return element, GeometryTransform.between(element.geometry, element.geometry)
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    width_m, height_m = _explicit_node_size(node)
    x_m = _number(position.get("x"), old_x) if element.movable else old_x
    y_m = _number(position.get("y"), old_y) if element.movable else old_y
    return transform_element(
        element,
        x_m=x_m,
        y_m=y_m,
        width_m=width_m,
        height_m=height_m,
    )


def _apply_queue_transform(
    queue: QueueSpec,
    nodes_by_id: dict[str, dict[str, Any]],
    owner_transforms: dict[str, GeometryTransform],
) -> QueueSpec:
    old_x, old_y, _, _ = queue.geometry.bounds()
    node = nodes_by_id.get(f"queue:{queue.id}")
    position = node.get("position") if node and isinstance(node.get("position"), dict) else {}
    queue_dx = _number(position.get("x"), old_x) - old_x
    queue_dy = _number(position.get("y"), old_y) - old_y
    owner_transform = owner_transforms.get(queue.owner_element_id)
    if abs(queue_dx) <= 1e-12 and abs(queue_dy) <= 1e-12 and owner_transform is not None:
        transformed_service_point = owner_transform.point(queue.service_point_m)
        queue_dx = transformed_service_point[0] - queue.service_point_m[0]
        queue_dy = transformed_service_point[1] - queue.service_point_m[1]
    return translate_queue(queue, queue_dx, queue_dy)


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
    raw_geometry = _raw_draft_geometry(node, data)
    geometry = _draft_geometry(node, data, raw_geometry)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    raw_ports = tuple(
        DesignPort.from_dict(port) for port in data.get("ports", ()) if isinstance(port, dict)
    )
    ports = transform_ports(raw_ports, GeometryTransform.between(raw_geometry, geometry))
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
    return _with_standard_ports(element, document)


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
    if not document.levels:
        node_id = node.get("id", "<unknown>")
        raise ValueError(
            f"Draft node {node_id!r} cannot be placed because the design has no levels"
        )
    return document.levels[0].id


def _raw_draft_geometry(node: dict[str, Any], data: dict[str, Any]) -> ElementGeometry:
    raw_geometry = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    if raw_geometry:
        geometry = ElementGeometry.from_dict(raw_geometry)
    else:
        geometry = ElementGeometry(
            shape="rect",
            width_m=max(_number(node.get("width"), _number(style.get("width"), 4.0)), 0.5),
            height_m=max(_number(node.get("height"), _number(style.get("height"), 3.0)), 0.5),
        )
    _ensure_finite_geometry(geometry)
    return geometry


def _ensure_finite_geometry(geometry: ElementGeometry) -> None:
    values = (
        geometry.x_m,
        geometry.y_m,
        geometry.width_m,
        geometry.height_m,
        geometry.rotation_deg,
        *(coordinate for point in geometry.points_m for coordinate in point),
    )
    if not all(isfinite(float(value)) for value in values):
        raise ValueError("React Flow geometry must contain only finite numbers")


def _draft_geometry(
    node: dict[str, Any],
    data: dict[str, Any],
    raw_geometry: ElementGeometry,
) -> ElementGeometry:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    width_m, height_m = _explicit_node_size(node)
    element = DesignElement(
        id="draft_geometry",
        kind=str(data.get("kind") or "obstacle"),
        level_id=str(data.get("level_id") or "draft"),
        geometry=raw_geometry,
        label="draft geometry",
        resizable=bool(data.get("resizable", True)),
    )
    transformed, _transform = transform_element(
        element,
        x_m=_number(position.get("x"), raw_geometry.x_m),
        y_m=_number(position.get("y"), raw_geometry.y_m),
        width_m=width_m,
        height_m=height_m,
    )
    return transformed.geometry


def _explicit_node_size(node: dict[str, Any]) -> tuple[float | None, float | None]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    size = data.get("inspector_size_m") if isinstance(data.get("inspector_size_m"), dict) else {}
    width = _positive_number(size.get("width"))
    height = _positive_number(size.get("height"))
    return width, height


def _positive_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed):
        raise ValueError("React Flow dimensions must be finite numbers")
    return parsed if parsed > 0 else None


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
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not isfinite(parsed):
        raise ValueError("React Flow positions and dimensions must be finite numbers")
    return parsed


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
