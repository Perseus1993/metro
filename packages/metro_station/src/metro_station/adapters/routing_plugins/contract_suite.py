"""Black-box contract suite for third-party routing plugins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from metro_station.application.routing_plugins import (
    ROUTE_NOT_FOUND,
    ROUTE_SUCCESS,
    EvacuationRoutingPort,
    EvacuationRoutingRequest,
    PassengerGroupFacts,
    RoutingEdge,
    RoutingNode,
    RoutingTopology,
    manifest_from_json,
)

from .process_host import RoutingPluginProcessHost


@dataclass(frozen=True)
class RoutingContractCaseResult:
    case_id: str
    passed: bool
    status: str
    message: str


@dataclass(frozen=True)
class RoutingContractReport:
    plugin_id: str
    plugin_version: str
    passed: bool
    cases: tuple[RoutingContractCaseResult, ...]
    active_processes_after: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "passed": self.passed,
            "cases": [asdict(case) for case in self.cases],
            "summary": {
                "passed": sum(case.passed for case in self.cases),
                "total": len(self.cases),
            },
            "active_processes_after": self.active_processes_after,
        }


def validate_plugin_file(
    manifest_path: str | Path,
    *,
    parameters: Mapping[str, Any] | None = None,
    timeout_seconds: float = 2.0,
) -> RoutingContractReport:
    path = Path(manifest_path).resolve()
    manifest = manifest_from_json(path.read_text(encoding="utf-8"))
    manifest.validate_parameters(parameters or {})
    host = RoutingPluginProcessHost(
        manifest,
        working_directory=path.parent,
        timeout_seconds=timeout_seconds,
    )
    try:
        return run_routing_contract_suite(host, parameters=parameters)
    finally:
        host.close()


def run_routing_contract_suite(
    algorithm: EvacuationRoutingPort,
    *,
    parameters: Mapping[str, Any] | None = None,
) -> RoutingContractReport:
    requests = _contract_requests(dict(parameters or {}))
    expected = _expected_statuses()
    results: list[RoutingContractCaseResult] = []
    first_route: tuple[str, ...] | None = None
    for request in requests:
        invocation = algorithm.invoke(request)
        result = _case_result(request, invocation, expected[request.request_id])
        if request.request_id == "case-01" and invocation.response is not None:
            first_route = invocation.response.node_ids
        if request.request_id == "case-10" and invocation.response is not None:
            deterministic = first_route == invocation.response.node_ids
            if not deterministic:
                result = RoutingContractCaseResult(
                    request.request_id, False, invocation.decision_log.status, "not deterministic"
                )
        results.append(result)
    active = int(getattr(algorithm, "active_process_count", 0))
    passed = all(result.passed for result in results) and active == 0
    return RoutingContractReport(
        algorithm.manifest.plugin_id,
        algorithm.manifest.plugin_version,
        passed,
        tuple(results),
        active,
    )


def _case_result(request, invocation, expected_status):
    actual = invocation.decision_log.status
    if invocation.failed:
        message = (
            f"{invocation.decision_log.failure_code}: {invocation.decision_log.failure_message}"
        )
        return RoutingContractCaseResult(request.request_id, False, actual, message)
    passed = invocation.response is not None and invocation.response.status == expected_status
    message = "ok" if passed else f"expected {expected_status}, got {actual}"
    return RoutingContractCaseResult(request.request_id, passed, actual, message)


def _contract_requests(parameters: dict[str, Any]) -> tuple[EvacuationRoutingRequest, ...]:
    topology = _contract_topology()
    specifications = (
        ("A", "D", (), 7),
        ("A", "D", ("ab",), 8),
        ("A", "D", ("ac",), 9),
        ("A", "D", ("ab", "ac"), 10),
        ("A", "D", ("bd",), 11),
        ("A", "D", ("cd",), 12),
        ("A", "A", (), 13),
        ("B", "D", (), 14),
        ("C", "D", (), 15),
        ("A", "D", (), 7),
    )
    return tuple(
        EvacuationRoutingRequest(
            request_id=f"case-{index:02d}",
            simulation_time_seconds=float(index),
            origin_node_id=origin,
            destination_node_id=destination,
            closed_edge_ids=closed,
            passenger_group=PassengerGroupFacts(index, "evacuate_station"),
            algorithm_seed=seed,
            topology=topology,
            parameters=parameters,
        )
        for index, (origin, destination, closed, seed) in enumerate(specifications, start=1)
    )


def _expected_statuses() -> dict[str, str]:
    return {
        f"case-{index:02d}": ROUTE_NOT_FOUND if index == 4 else ROUTE_SUCCESS
        for index in range(1, 11)
    }


def _contract_topology() -> RoutingTopology:
    nodes = tuple(
        RoutingNode(node_id, "L1", x, y, "zone")
        for node_id, x, y in (("A", 0.0, 0.0), ("B", 1.0, 0.0), ("C", 1.0, 1.0), ("D", 2.0, 0.0))
    )
    edges = tuple(
        RoutingEdge(*values)
        for values in (
            ("ab", "A", "B", 1.0, "walk"),
            ("bd", "B", "D", 1.0, "walk"),
            ("ac", "A", "C", 2.0, "walk"),
            ("cd", "C", "D", 2.0, "walk"),
            ("bc", "B", "C", 0.5, "walk"),
        )
    )
    return RoutingTopology("contract-topology", nodes, edges)
