from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SCHEMA_VERSION = "metro-station-design/v1"

ElementKind = Literal[
    "entrance",
    "walkable_area",
    "platform_edge",
    "gate",
    "escalator",
    "stairs",
    "elevator",
    "shop",
    "service_room",
    "equipment",
    "obstacle",
]

QueueKind = Literal["lane", "grid", "holding_area"]
ConnectionKind = Literal["walk", "vertical", "service"]
GeometryShape = Literal["rect", "polygon", "polyline", "point"]


@dataclass(frozen=True)
class DesignConstraints:
    """Hard limits the editor must enforce before a design reaches simulation."""

    max_levels: int = 3
    min_floor_height_m: float = 3.0
    max_floor_height_m: float = 12.0
    max_depth_m: float = 28.0
    canvas_width_m: float = 120.0
    canvas_height_m: float = 80.0
    grid_size_m: float = 0.5
    allowed_facility_kinds: tuple[str, ...] = (
        "gate",
        "entrance",
        "escalator",
        "stairs",
        "elevator",
        "shop",
        "service_room",
        "equipment",
        "obstacle",
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_levels": self.max_levels,
            "min_floor_height_m": self.min_floor_height_m,
            "max_floor_height_m": self.max_floor_height_m,
            "max_depth_m": self.max_depth_m,
            "canvas_width_m": self.canvas_width_m,
            "canvas_height_m": self.canvas_height_m,
            "grid_size_m": self.grid_size_m,
            "allowed_facility_kinds": list(self.allowed_facility_kinds),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DesignConstraints:
        values = dict(payload)
        if "allowed_facility_kinds" in values:
            values["allowed_facility_kinds"] = tuple(values["allowed_facility_kinds"])
        return cls(**values)


@dataclass(frozen=True)
class LevelSpec:
    id: str
    label: str
    elevation_m: float
    floor_to_floor_height_m: float
    order: int
    footprint: tuple[tuple[float, float], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "elevation_m": self.elevation_m,
            "floor_to_floor_height_m": self.floor_to_floor_height_m,
            "order": self.order,
            "footprint": [list(point) for point in self.footprint],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LevelSpec:
        values = dict(payload)
        values["footprint"] = tuple(tuple(point) for point in values.get("footprint", ()))
        return cls(**values)


@dataclass(frozen=True)
class ElementGeometry:
    shape: GeometryShape
    x_m: float = 0.0
    y_m: float = 0.0
    width_m: float = 0.0
    height_m: float = 0.0
    rotation_deg: float = 0.0
    points_m: tuple[tuple[float, float], ...] = ()

    def bounds(self) -> tuple[float, float, float, float]:
        if self.shape in {"polygon", "polyline"} and self.points_m:
            xs = [point[0] for point in self.points_m]
            ys = [point[1] for point in self.points_m]
            return min(xs), min(ys), max(xs), max(ys)
        return self.x_m, self.y_m, self.x_m + self.width_m, self.y_m + self.height_m

    def center(self) -> tuple[float, float]:
        min_x, min_y, max_x, max_y = self.bounds()
        return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

    def moved_to(self, x_m: float, y_m: float) -> ElementGeometry:
        if self.shape in {"polygon", "polyline"} and self.points_m:
            old_x, old_y, _, _ = self.bounds()
            dx = x_m - old_x
            dy = y_m - old_y
            return ElementGeometry(
                shape=self.shape,
                x_m=x_m,
                y_m=y_m,
                width_m=self.width_m,
                height_m=self.height_m,
                rotation_deg=self.rotation_deg,
                points_m=tuple((px + dx, py + dy) for px, py in self.points_m),
            )
        return ElementGeometry(
            shape=self.shape,
            x_m=x_m,
            y_m=y_m,
            width_m=self.width_m,
            height_m=self.height_m,
            rotation_deg=self.rotation_deg,
            points_m=self.points_m,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape,
            "x_m": self.x_m,
            "y_m": self.y_m,
            "width_m": self.width_m,
            "height_m": self.height_m,
            "rotation_deg": self.rotation_deg,
            "points_m": [list(point) for point in self.points_m],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ElementGeometry:
        values = dict(payload)
        values["points_m"] = tuple(tuple(point) for point in values.get("points_m", ()))
        return cls(**values)


@dataclass(frozen=True)
class QueueSpec:
    id: str
    owner_element_id: str
    kind: QueueKind
    level_id: str
    geometry: ElementGeometry
    service_point_m: tuple[float, float]
    capacity: int
    spacing_m: float = 0.8
    direction_deg: float = 0.0
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner_element_id": self.owner_element_id,
            "kind": self.kind,
            "level_id": self.level_id,
            "geometry": self.geometry.as_dict(),
            "service_point_m": list(self.service_point_m),
            "capacity": self.capacity,
            "spacing_m": self.spacing_m,
            "direction_deg": self.direction_deg,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> QueueSpec:
        values = dict(payload)
        values["geometry"] = ElementGeometry.from_dict(values["geometry"])
        values["service_point_m"] = tuple(values["service_point_m"])
        return cls(**values)


@dataclass(frozen=True)
class DesignElement:
    id: str
    kind: ElementKind
    level_id: str
    geometry: ElementGeometry
    label: str
    role: str = "facility"
    movable: bool = True
    resizable: bool = True
    connects_levels: tuple[str, ...] = ()
    capacity: int | None = None
    queue_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    gate_direction: str | None = None
    direction: str | None = None
    line_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "level_id": self.level_id,
            "geometry": self.geometry.as_dict(),
            "label": self.label,
            "role": self.role,
            "movable": self.movable,
            "resizable": self.resizable,
            "connects_levels": list(self.connects_levels),
            "capacity": self.capacity,
            "queue_policy": self.queue_policy,
            "metadata": self.metadata,
            "gate_direction": self.gate_direction,
            "direction": self.direction,
            "line_id": self.line_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DesignElement:
        values = dict(payload)
        values["geometry"] = ElementGeometry.from_dict(values["geometry"])
        values["connects_levels"] = tuple(values.get("connects_levels", ()))
        metadata = dict(values.get("metadata", {}))
        values.setdefault("gate_direction", metadata.get("gate_direction"))
        values.setdefault("direction", metadata.get("direction"))
        values.setdefault("line_id", metadata.get("line_id"))
        return cls(**values)


@dataclass(frozen=True)
class DesignConnection:
    id: str
    source_id: str
    target_id: str
    kind: ConnectionKind = "walk"
    bidirectional: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "bidirectional": self.bidirectional,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DesignConnection:
        return cls(**payload)


@dataclass(frozen=True)
class StationDesignDocument:
    id: str
    label: str
    template_id: str
    constraints: DesignConstraints
    levels: tuple[LevelSpec, ...]
    elements: tuple[DesignElement, ...]
    queues: tuple[QueueSpec, ...] = ()
    connections: tuple[DesignConnection, ...] = ()
    schema_version: str = SCHEMA_VERSION
    units: str = "meters"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "label": self.label,
            "template_id": self.template_id,
            "units": self.units,
            "constraints": self.constraints.as_dict(),
            "levels": [level.as_dict() for level in self.levels],
            "elements": [element.as_dict() for element in self.elements],
            "queues": [queue.as_dict() for queue in self.queues],
            "connections": [connection.as_dict() for connection in self.connections],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StationDesignDocument:
        return cls(
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            id=payload["id"],
            label=payload["label"],
            template_id=payload["template_id"],
            units=payload.get("units", "meters"),
            constraints=DesignConstraints.from_dict(payload["constraints"]),
            levels=tuple(LevelSpec.from_dict(item) for item in payload["levels"]),
            elements=tuple(DesignElement.from_dict(item) for item in payload["elements"]),
            queues=tuple(QueueSpec.from_dict(item) for item in payload.get("queues", ())),
            connections=tuple(
                DesignConnection.from_dict(item) for item in payload.get("connections", ())
            ),
            metadata=payload.get("metadata", {}),
        )

    def element_by_id(self) -> dict[str, DesignElement]:
        return {element.id: element for element in self.elements}

    def level_by_id(self) -> dict[str, LevelSpec]:
        return {level.id: level for level in self.levels}
