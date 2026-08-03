"""Build decision-log evidence for routing algorithm invocations."""

from __future__ import annotations

from typing import Any

from metro_station.application.routing_plugins import (
    AlgorithmManifest,
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
    RoutingDecisionLog,
)


def response_decision_log(
    manifest: AlgorithmManifest,
    request: EvacuationRoutingRequest,
    response: EvacuationRoutingResponse,
    duration_ms: float,
    *,
    stderr: str = "",
) -> RoutingDecisionLog:
    return RoutingDecisionLog(
        request_id=request.request_id,
        plugin_id=manifest.plugin_id,
        plugin_version=manifest.plugin_version,
        api_version=manifest.api_version,
        status=response.status,
        compute_duration_ms=duration_ms,
        parameters=request.parameters,
        topology_fingerprint=request.topology.semantic_fingerprint,
        node_ids=response.node_ids,
        edge_ids=response.edge_ids,
        diagnostics=response.diagnostics.as_dict(),
        stderr=_stderr_excerpt(stderr),
    )


def failed_decision_log(
    manifest: AlgorithmManifest,
    request: EvacuationRoutingRequest,
    duration_ms: float,
    *,
    code: str,
    message: str,
    stderr: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> RoutingDecisionLog:
    return RoutingDecisionLog(
        request_id=request.request_id,
        plugin_id=manifest.plugin_id,
        plugin_version=manifest.plugin_version,
        api_version=manifest.api_version,
        status="failed",
        compute_duration_ms=duration_ms,
        parameters=request.parameters,
        topology_fingerprint=request.topology.semantic_fingerprint,
        diagnostics=dict(diagnostics or {}),
        failure_code=code,
        failure_message=message,
        stderr=_stderr_excerpt(stderr),
    )


def _stderr_excerpt(stderr: str, limit: int = 8_000) -> str:
    return str(stderr or "")[-limit:]
