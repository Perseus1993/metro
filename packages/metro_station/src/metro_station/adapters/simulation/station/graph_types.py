from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Point = tuple[float, float]


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    level_id: str
    position: Point
    kind: str
    element_id: str | None
    line_id: str | None = None
    direction: str | None = None
    facility_stage: str | None = None
    tactical_anchor: bool = False


@dataclass(frozen=True)
class GraphEdge:
    from_node: str
    to_node: str
    kind: str
    cost: float
    level_change: bool
    bidirectional: bool = False
    facility_stage: str | None = None
    origin: str = "unknown"
    detail_id: str | None = None


@dataclass(frozen=True)
class GraphCompileDiagnostic:
    severity: str
    code: str
    message: str
    connection_id: str | None = None
    element_id: str | None = None
    from_node: str | None = None
    to_node: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "connection_id": self.connection_id,
            "element_id": self.element_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RouteSegment:
    node_ids: tuple[str, ...]
    positions: tuple[Point, ...]
    edges: tuple[GraphEdge, ...]
