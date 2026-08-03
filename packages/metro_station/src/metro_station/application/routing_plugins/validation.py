"""Cross-contract validation for evacuation-routing responses."""

from __future__ import annotations

from .contracts import (
    ROUTE_NOT_FOUND,
    ROUTE_SUCCESS,
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
)


def validate_routing_response(
    request: EvacuationRoutingRequest,
    response: EvacuationRoutingResponse,
) -> None:
    if response.request_id != request.request_id:
        raise ValueError("routing response request_id does not match the request")
    if response.status == ROUTE_NOT_FOUND:
        if response.node_ids or response.edge_ids or response.cost is not None:
            raise ValueError("no_route response must have empty paths and null cost")
        return
    if response.status != ROUTE_SUCCESS:
        raise ValueError(f"unsupported routing response status: {response.status!r}")
    if response.cost is None:
        raise ValueError("successful routing response requires cost")
    if not response.node_ids:
        raise ValueError("successful routing response requires node_ids")
    if response.node_ids[0] != request.origin_node_id:
        raise ValueError("routing path must start at the requested origin")
    if response.node_ids[-1] != request.destination_node_id:
        raise ValueError("routing path must end at the requested destination")
    if len(response.edge_ids) != max(0, len(response.node_ids) - 1):
        raise ValueError("routing edge_ids must connect each adjacent node pair")
    if len(set(response.node_ids)) != len(response.node_ids):
        raise ValueError("routing path must not contain node cycles")
    _validate_path_membership(request, response)


def _validate_path_membership(
    request: EvacuationRoutingRequest,
    response: EvacuationRoutingResponse,
) -> None:
    node_ids = {node.node_id for node in request.topology.nodes}
    unknown_nodes = sorted(set(response.node_ids) - node_ids)
    if unknown_nodes:
        raise ValueError("routing response contains unknown nodes: " + ", ".join(unknown_nodes))
    edge_by_id = {edge.edge_id: edge for edge in request.topology.edges}
    unknown_edges = sorted(set(response.edge_ids) - set(edge_by_id))
    if unknown_edges:
        raise ValueError("routing response contains unknown edges: " + ", ".join(unknown_edges))
    closed = set(request.closed_edge_ids)
    for index, edge_id in enumerate(response.edge_ids):
        if edge_id in closed:
            raise ValueError(f"routing response uses closed edge {edge_id!r}")
        edge = edge_by_id[edge_id]
        pair = response.node_ids[index : index + 2]
        if pair != (edge.from_node, edge.to_node):
            raise ValueError(f"routing edge {edge_id!r} does not match adjacent nodes")
