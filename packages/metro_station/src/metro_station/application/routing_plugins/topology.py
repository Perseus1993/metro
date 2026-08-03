"""Immutable topology snapshot used by evacuation-routing plugins."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from math import isfinite
from typing import Any, Mapping
import json

from .manifest import _require_json_compatible


EVACUATION_TOPOLOGY_SCHEMA_VERSION = "evacuation-topology/v1"


@dataclass(frozen=True)
class RoutingNode:
    node_id: str
    level_id: str
    x: float
    y: float
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.level_id.strip() or not self.kind.strip():
            raise ValueError("routing node id, level and kind must not be blank")
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("routing node coordinates must be finite")
        _require_json_compatible(self.metadata, "routing node metadata")

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level_id": self.level_id,
            "x": float(self.x),
            "y": float(self.y),
            "kind": self.kind,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RoutingNode:
        return cls(**dict(payload))


@dataclass(frozen=True)
class RoutingEdge:
    edge_id: str
    from_node: str
    to_node: str
    cost: float
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(
            not value.strip() for value in (self.edge_id, self.from_node, self.to_node, self.kind)
        ):
            raise ValueError("routing edge id, endpoints and kind must not be blank")
        if not isfinite(self.cost) or self.cost < 0:
            raise ValueError("routing edge cost must be finite and >= 0")
        _require_json_compatible(self.metadata, "routing edge metadata")

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "cost": float(self.cost),
            "kind": self.kind,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RoutingEdge:
        return cls(**dict(payload))


@dataclass(frozen=True)
class RoutingTopology:
    topology_id: str
    nodes: tuple[RoutingNode, ...]
    edges: tuple[RoutingEdge, ...]
    schema_version: str = EVACUATION_TOPOLOGY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVACUATION_TOPOLOGY_SCHEMA_VERSION:
            raise ValueError(f"unsupported routing topology schema: {self.schema_version!r}")
        if not self.topology_id.strip() or not self.nodes:
            raise ValueError("routing topology requires topology_id and nodes")
        node_ids = _unique_ids(self.nodes, "node_id", "routing node")
        _unique_ids(self.edges, "edge_id", "routing edge")
        edge_node_ids = {edge.from_node for edge in self.edges} | {
            edge.to_node for edge in self.edges
        }
        unknown = sorted(edge_node_ids - node_ids)
        if unknown:
            raise ValueError("routing edges reference unknown nodes: " + ", ".join(unknown))

    @property
    def semantic_fingerprint(self) -> str:
        payload = json.dumps(self.semantic_payload(), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "topology_id": self.topology_id,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_payload(),
            "semantic_fingerprint": self.semantic_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RoutingTopology:
        values = dict(payload)
        expected_fingerprint = values.pop("semantic_fingerprint", None)
        values["nodes"] = tuple(RoutingNode.from_dict(item) for item in values.get("nodes", ()))
        values["edges"] = tuple(RoutingEdge.from_dict(item) for item in values.get("edges", ()))
        topology = cls(**values)
        if expected_fingerprint and expected_fingerprint != topology.semantic_fingerprint:
            raise ValueError("routing topology semantic fingerprint mismatch")
        return topology


def _unique_ids(items: tuple[Any, ...], attribute: str, label: str) -> set[str]:
    values = [str(getattr(item, attribute)) for item in items]
    if len(set(values)) != len(values):
        raise ValueError(f"{label} ids must be unique")
    return set(values)
