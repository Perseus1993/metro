from __future__ import annotations

from dataclasses import dataclass


Point = tuple[float, float]


@dataclass(frozen=True)
class LayoutNode:
    node_id: str
    label: str
    position: Point
    level: str


@dataclass(frozen=True)
class LayoutEdge:
    from_node: str
    to_node: str
    label: str
