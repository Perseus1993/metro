"""Versioned evacuation-routing request and response contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping

from .manifest import _require_json_compatible
from .topology import RoutingTopology


EVACUATION_ROUTING_SCHEMA_VERSION = "evacuation-routing/v1"
ROUTE_SUCCESS = "success"
ROUTE_NOT_FOUND = "no_route"
ROUTE_STATUSES = frozenset({ROUTE_SUCCESS, ROUTE_NOT_FOUND})


@dataclass(frozen=True)
class PassengerGroupFacts:
    group_size: int
    intent: str
    mobility_profile: str = "default"
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.group_size < 1:
            raise ValueError("passenger group_size must be >= 1")
        if not self.intent.strip() or not self.mobility_profile.strip():
            raise ValueError("passenger intent and mobility_profile must not be blank")
        _require_json_compatible(self.attributes, "passenger group attributes")

    def as_dict(self) -> dict[str, Any]:
        return {
            "group_size": int(self.group_size),
            "intent": self.intent,
            "mobility_profile": self.mobility_profile,
            "attributes": deepcopy(self.attributes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PassengerGroupFacts:
        return cls(**dict(payload))


@dataclass(frozen=True)
class RoutingDiagnostics:
    expanded_nodes: int
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expanded_nodes < 0 or not self.message.strip():
            raise ValueError("routing diagnostics require expanded_nodes >= 0 and a message")
        _require_json_compatible(self.metadata, "routing diagnostics metadata")

    def as_dict(self) -> dict[str, Any]:
        return {
            "expanded_nodes": int(self.expanded_nodes),
            "message": self.message,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RoutingDiagnostics:
        return cls(**dict(payload))


@dataclass(frozen=True)
class EvacuationRoutingRequest:
    request_id: str
    simulation_time_seconds: float
    origin_node_id: str
    destination_node_id: str
    closed_edge_ids: tuple[str, ...]
    passenger_group: PassengerGroupFacts
    algorithm_seed: int
    topology: RoutingTopology
    parameters: dict[str, Any] = field(default_factory=dict)
    schema_version: str = EVACUATION_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVACUATION_ROUTING_SCHEMA_VERSION:
            raise ValueError(f"unsupported evacuation routing schema: {self.schema_version!r}")
        if not self.request_id.strip():
            raise ValueError("routing request_id must not be blank")
        if not isfinite(self.simulation_time_seconds) or self.simulation_time_seconds < 0:
            raise ValueError("routing simulation time must be finite and >= 0")
        if self.algorithm_seed < 0:
            raise ValueError("routing algorithm_seed must be >= 0")
        node_ids = {node.node_id for node in self.topology.nodes}
        for label, node_id in (
            ("origin", self.origin_node_id),
            ("destination", self.destination_node_id),
        ):
            if node_id not in node_ids:
                raise ValueError(f"routing {label} references unknown node {node_id!r}")
        edge_ids = {edge.edge_id for edge in self.topology.edges}
        unknown_closed = sorted(set(self.closed_edge_ids) - edge_ids)
        if unknown_closed:
            raise ValueError("closed_edge_ids contains unknown edges: " + ", ".join(unknown_closed))
        if len(set(self.closed_edge_ids)) != len(self.closed_edge_ids):
            raise ValueError("closed_edge_ids must not contain duplicates")
        _require_json_compatible(self.parameters, "routing parameters")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "simulation_time_seconds": float(self.simulation_time_seconds),
            "origin_node_id": self.origin_node_id,
            "destination_node_id": self.destination_node_id,
            "closed_edge_ids": list(self.closed_edge_ids),
            "passenger_group": self.passenger_group.as_dict(),
            "algorithm_seed": int(self.algorithm_seed),
            "topology": self.topology.as_dict(),
            "parameters": deepcopy(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvacuationRoutingRequest:
        values = dict(payload)
        values["closed_edge_ids"] = tuple(str(item) for item in values.get("closed_edge_ids", ()))
        values["passenger_group"] = PassengerGroupFacts.from_dict(values["passenger_group"])
        values["topology"] = RoutingTopology.from_dict(values["topology"])
        values["parameters"] = deepcopy(values.get("parameters", {}))
        return cls(**values)


@dataclass(frozen=True)
class EvacuationRoutingResponse:
    request_id: str
    status: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    cost: float | None
    diagnostics: RoutingDiagnostics
    schema_version: str = EVACUATION_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVACUATION_ROUTING_SCHEMA_VERSION:
            raise ValueError(f"unsupported evacuation routing schema: {self.schema_version!r}")
        if not self.request_id.strip() or self.status not in ROUTE_STATUSES:
            raise ValueError("routing response requires request_id and a supported status")
        if self.cost is not None and (not isfinite(self.cost) or self.cost < 0):
            raise ValueError("routing response cost must be finite and >= 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "status": self.status,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "cost": self.cost,
            "diagnostics": self.diagnostics.as_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvacuationRoutingResponse:
        values = dict(payload)
        if "diagnostics" not in values:
            raise ValueError("routing response is missing diagnostics")
        values["node_ids"] = tuple(str(item) for item in values.get("node_ids", ()))
        values["edge_ids"] = tuple(str(item) for item in values.get("edge_ids", ()))
        values["diagnostics"] = RoutingDiagnostics.from_dict(values["diagnostics"])
        return cls(**values)
