"""Bridge evacuation passengers to the public routing-algorithm port."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from metro_station.application.routing_plugins import (
    ROUTE_NOT_FOUND,
    EvacuationRoutingPort,
    EvacuationRoutingRequest,
    PassengerGroupFacts,
)

from ...routing_plugins.station_topology import (
    closed_topology_edge_ids,
    station_graph_topology,
)
from ..planning.plan import AgentIntent


class RoutingPluginRunError(RuntimeError):
    """An injected routing algorithm cannot provide a legal route."""


class RuntimeEvacuationRoutingService:
    """Build requests, invoke the algorithm, and retain decision evidence."""

    def __init__(
        self,
        algorithm: EvacuationRoutingPort | None,
        station_graph: Any,
        *,
        parameters: Mapping[str, Any] | None,
        base_seed: int,
    ) -> None:
        self.algorithm = algorithm
        self.topology = None if station_graph is None else station_graph_topology(station_graph)
        self.parameters = deepcopy(dict(parameters or {}))
        self.base_seed = int(base_seed)
        self.request_count = 0
        self.terminal_failure_message: str | None = None
        if algorithm is not None:
            algorithm.manifest.validate_parameters(self.parameters)

    def enabled_for(self, passenger: Any) -> bool:
        return (
            self.algorithm is not None
            and self.topology is not None
            and passenger.intent == AgentIntent.EVACUATE_STATION.value
        )

    def route_node_ids(
        self,
        model: Any,
        passenger: Any,
        origin_node_id: str,
        destination_node_id: str,
    ) -> tuple[str, ...]:
        if self.algorithm is None or self.topology is None:
            raise RuntimeError("evacuation routing service is not configured")
        self.raise_if_failed()
        request = self._request(model, passenger, origin_node_id, destination_node_id)
        invocation = self.algorithm.invoke(request)
        model.routing_decision_logs.append(invocation.decision_log)
        if invocation.failed:
            log = invocation.decision_log
            self._fail(f"{log.failure_code}: {log.failure_message}")
        response = invocation.response
        assert response is not None
        if response.status == ROUTE_NOT_FOUND:
            self._fail(f"no route from {origin_node_id!r} to {destination_node_id!r}")
        return tuple(response.node_ids[1:])

    def raise_if_failed(self) -> None:
        if self.terminal_failure_message is None:
            return
        raise RoutingPluginRunError(self.terminal_failure_message)

    def _fail(self, message: str) -> None:
        self.terminal_failure_message = message
        raise RoutingPluginRunError(message)

    def _request(self, model, passenger, origin_node_id, destination_node_id):
        topology = self.topology
        if topology is None:
            raise RuntimeError("evacuation routing topology is unavailable")
        self.request_count += 1
        passenger_id = int(passenger.unique_id)
        return EvacuationRoutingRequest(
            request_id=f"route:{model.step_index}:{passenger_id}:{self.request_count}",
            simulation_time_seconds=float(model.current_time_seconds),
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            closed_edge_ids=closed_topology_edge_ids(model, topology),
            passenger_group=PassengerGroupFacts(
                int(passenger.group_size),
                str(passenger.intent),
                attributes={
                    "prefers_elevator": bool(passenger.prefers_elevator),
                    "prefers_stairs": bool(passenger.prefers_stairs),
                },
            ),
            algorithm_seed=self._request_seed(passenger_id),
            topology=topology,
            parameters=self.parameters,
        )

    def _request_seed(self, passenger_id: int) -> int:
        return (self.base_seed + passenger_id * 1_000_003 + self.request_count) % (2**63)
