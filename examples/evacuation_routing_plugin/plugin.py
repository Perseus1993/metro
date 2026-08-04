"""Standalone evacuation-routing example; imports no metro-station modules."""

from __future__ import annotations

import json
import sys
from heapq import heappop, heappush


def route(request: dict) -> dict:
    origin = request["origin_node_id"]
    destination = request["destination_node_id"]
    if origin == destination:
        return response(request, "success", [origin], [], 0.0, 1, "route_found")
    multiplier = float(request.get("parameters", {}).get("cost_multiplier", 1.0))
    closed = set(request.get("closed_edge_ids", []))
    adjacency: dict[str, list[tuple[str, str, float]]] = {}
    for edge in request["topology"]["edges"]:
        if edge["edge_id"] in closed:
            continue
        adjacency.setdefault(edge["from_node"], []).append(
            (edge["to_node"], edge["edge_id"], float(edge["cost"]) * multiplier)
        )
    for edges in adjacency.values():
        edges.sort(key=lambda item: (item[0], item[1]))
    return search(request, adjacency)


def search(request: dict, adjacency: dict) -> dict:
    origin = request["origin_node_id"]
    destination = request["destination_node_id"]
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
            nodes, edges = reconstruct(origin, destination, previous)
            return response(request, "success", nodes, edges, distance, expanded, "route_found")
        for to_node, edge_id, cost in adjacency.get(node_id, []):
            candidate = distance + cost
            if candidate >= distances.get(to_node, float("inf")):
                continue
            distances[to_node] = candidate
            previous[to_node] = (node_id, edge_id)
            heappush(heap, (candidate, to_node))
    return response(request, "no_route", [], [], None, expanded, "no_route")


def reconstruct(origin: str, destination: str, previous: dict) -> tuple[list[str], list[str]]:
    nodes = [destination]
    edges: list[str] = []
    current = destination
    while current != origin:
        current, edge_id = previous[current]
        nodes.append(current)
        edges.append(edge_id)
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def response(request, status, nodes, edges, cost, expanded, message) -> dict:
    return {
        "schema_version": "evacuation-routing/v1",
        "request_id": request["request_id"],
        "status": status,
        "node_ids": nodes,
        "edge_ids": edges,
        "cost": cost,
        "diagnostics": {
            "expanded_nodes": expanded,
            "message": message,
            "metadata": {},
        },
    }


def main() -> int:
    try:
        envelope = json.loads(sys.stdin.readline())
        result = route(envelope["request"])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    except Exception as exc:
        print(f"plugin error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
