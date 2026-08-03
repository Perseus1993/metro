"""Execution evidence and application port for routing algorithms."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Protocol

from .contracts import EvacuationRoutingRequest, EvacuationRoutingResponse
from .manifest import AlgorithmManifest


ROUTING_DECISION_LOG_SCHEMA_VERSION = "routing-decision-log/v1"
EXECUTION_STATUSES = frozenset({"success", "no_route", "failed"})


@dataclass(frozen=True)
class RoutingDecisionLog:
    request_id: str
    plugin_id: str
    plugin_version: str
    api_version: str
    status: str
    compute_duration_ms: float
    parameters: dict[str, Any]
    topology_fingerprint: str
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    stderr: str = ""
    schema_version: str = ROUTING_DECISION_LOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ROUTING_DECISION_LOG_SCHEMA_VERSION:
            raise ValueError(f"unsupported routing decision log schema: {self.schema_version!r}")
        if self.status not in EXECUTION_STATUSES:
            raise ValueError(f"unsupported routing execution status: {self.status!r}")
        if not self.topology_fingerprint.strip():
            raise ValueError("routing decision log requires topology_fingerprint")
        if not isfinite(self.compute_duration_ms) or self.compute_duration_ms < 0:
            raise ValueError("routing compute duration must be finite and >= 0")
        if self.status == "failed" and (not self.failure_code or not self.failure_message):
            raise ValueError("failed routing decisions require failure code and message")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "api_version": self.api_version,
            "status": self.status,
            "compute_duration_ms": round(float(self.compute_duration_ms), 6),
            "parameters": deepcopy(self.parameters),
            "topology_fingerprint": self.topology_fingerprint,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "diagnostics": deepcopy(self.diagnostics),
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
            "stderr": self.stderr,
        }


@dataclass(frozen=True)
class RoutingInvocationResult:
    response: EvacuationRoutingResponse | None
    decision_log: RoutingDecisionLog

    def __post_init__(self) -> None:
        if self.decision_log.status == "failed" and self.response is not None:
            raise ValueError("failed routing invocation must not contain a response")
        if self.decision_log.status != "failed" and self.response is None:
            raise ValueError("successful routing invocation requires a response")

    @property
    def failed(self) -> bool:
        return self.decision_log.status == "failed"


class EvacuationRoutingPort(Protocol):
    @property
    def manifest(self) -> AlgorithmManifest: ...

    def invoke(self, request: EvacuationRoutingRequest) -> RoutingInvocationResult: ...
