"""Built-in deterministic shortest-path evacuation router."""

from __future__ import annotations

from heapq import heappop, heappush
from time import perf_counter

from metro_station.application.routing_plugins import (
    ROUTE_NOT_FOUND,
    ROUTE_SUCCESS,
    AlgorithmManifest,
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
    RoutingDiagnostics,
    RoutingInvocationResult,
    validate_routing_response,
)

from .decision_evidence import response_decision_log


BASELINE_PLUGIN_ID = "metro.shortest_path"


class BaselineEvacuationRouter:
    """Reference Dijkstra implementation for the public routing contract."""

    def __init__(self) -> None:
        self._manifest = AlgorithmManifest(
            plugin_id=BASELINE_PLUGIN_ID,
            plugin_version="1.0.0",
            entry_point=("builtin",),
            parameter_schema={
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"cost_multiplier": {"type": "number", "exclusiveMinimum": 0}},
                "additionalProperties": False,
            },
            capabilities=("closures", "deterministic_seed", "diagnostics", "group_facts"),
            metadata={"label": "Built-in shortest path baseline"},
        )

    @property
    def manifest(self) -> AlgorithmManifest:
        return self._manifest

    def invoke(self, request: EvacuationRoutingRequest) -> RoutingInvocationResult:
        parameters = self.manifest.validate_parameters(request.parameters)
        started = perf_counter()
        response = _shortest_path_response(request, float(parameters.get("cost_multiplier", 1.0)))
        duration_ms = (perf_counter() - started) * 1_000.0
        validate_routing_response(request, response)
        return RoutingInvocationResult(
            response,
            response_decision_log(self.manifest, request, response, duration_ms),
        )


def _shortest_path_response(
    request: EvacuationRoutingRequest,
    multiplier: float,
) -> EvacuationRoutingResponse:
    origin = request.origin_node_id
    destination = request.destination_node_id
    if origin == destination:
        return _success_response(request, (origin,), (), 0.0, 1)
    adjacency = _adjacency(request, multiplier)
    heap: list[tuple[float, str]] = [(0.0, origin)]
    distances = {origin: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    expanded = 0
    while heap:
        distance, node_id = heappop(heap)
        if distance > distances.get(node_id, float("inf")):
            continue
        expanded += 1
        if node_id == destination:
            nodes, edges = _reconstruct(origin, destination, previous)
            return _success_response(request, nodes, edges, distance, expanded)
        for to_node, edge_id, cost in adjacency.get(node_id, ()):
            candidate = distance + cost
            if candidate >= distances.get(to_node, float("inf")):
                continue
            distances[to_node] = candidate
            previous[to_node] = (node_id, edge_id)
            heappush(heap, (candidate, to_node))
    return EvacuationRoutingResponse(
        request_id=request.request_id,
        status=ROUTE_NOT_FOUND,
        node_ids=(),
        edge_ids=(),
        cost=None,
        diagnostics=RoutingDiagnostics(expanded, "no_route"),
    )


def _adjacency(request: EvacuationRoutingRequest, multiplier: float):
    closed = set(request.closed_edge_ids)
    adjacency: dict[str, list[tuple[str, str, float]]] = {}
    for edge in request.topology.edges:
        if edge.edge_id in closed:
            continue
        adjacency.setdefault(edge.from_node, []).append(
            (edge.to_node, edge.edge_id, edge.cost * multiplier)
        )
    for edges in adjacency.values():
        edges.sort(key=lambda item: (item[0], item[1]))
    return adjacency


def _reconstruct(origin: str, destination: str, previous):
    nodes = [destination]
    edges: list[str] = []
    current = destination
    while current != origin:
        parent, edge_id = previous[current]
        nodes.append(parent)
        edges.append(edge_id)
        current = parent
    nodes.reverse()
    edges.reverse()
    return tuple(nodes), tuple(edges)


def _success_response(request, nodes, edges, cost, expanded):
    return EvacuationRoutingResponse(
        request_id=request.request_id,
        status=ROUTE_SUCCESS,
        node_ids=nodes,
        edge_ids=edges,
        cost=cost,
        diagnostics=RoutingDiagnostics(expanded, "route_found"),
    )
