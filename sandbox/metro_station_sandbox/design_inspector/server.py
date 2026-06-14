from __future__ import annotations

import json
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..design.react_flow_adapter import (
    apply_react_flow_edges,
    apply_react_flow_nodes,
    to_react_flow,
)
from ..design.templates import create_design, topology_templates
from ..design.validation import validate_design
from ..station.graph import StationGraph


ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_ID = "visual_demo_station"
COMPONENT_PALETTE = (
    {
        "id": "entrance",
        "label": "Entrance",
        "kind": "entrance",
        "role": "facility",
        "node_type": "facilityNode",
        "size_m": {"width": 5.0, "height": 5.0},
    },
    {
        "id": "entry_gate",
        "label": "Entry gate",
        "kind": "gate",
        "role": "facility",
        "node_type": "facilityNode",
        "gate_direction": "entry",
        "capacity": 1,
        "size_m": {"width": 8.0, "height": 5.0},
    },
    {
        "id": "exit_gate",
        "label": "Exit gate",
        "kind": "gate",
        "role": "facility",
        "node_type": "facilityNode",
        "gate_direction": "exit",
        "capacity": 1,
        "size_m": {"width": 8.0, "height": 5.0},
    },
    {
        "id": "bidirectional_gate",
        "label": "Bidir gate",
        "kind": "gate",
        "role": "facility",
        "node_type": "facilityNode",
        "gate_direction": "bidirectional",
        "capacity": 1,
        "size_m": {"width": 8.0, "height": 5.0},
    },
    {
        "id": "platform_edge",
        "label": "Platform edge",
        "kind": "platform_edge",
        "role": "facility",
        "node_type": "facilityNode",
        "direction": "down",
        "line_id": "L1",
        "size_m": {"width": 7.0, "height": 3.0},
    },
    {
        "id": "down_escalator",
        "label": "Down escalator",
        "kind": "escalator",
        "role": "vertical_connector",
        "node_type": "verticalConnector",
        "direction": "down",
        "capacity": 75,
        "size_m": {"width": 7.0, "height": 12.0},
    },
    {
        "id": "stairs",
        "label": "Stairs",
        "kind": "stairs",
        "role": "vertical_connector",
        "node_type": "verticalConnector",
        "direction": "both",
        "capacity": 120,
        "size_m": {"width": 8.0, "height": 12.0},
    },
    {
        "id": "elevator",
        "label": "Elevator",
        "kind": "elevator",
        "role": "vertical_connector",
        "node_type": "verticalConnector",
        "direction": "both",
        "capacity": 16,
        "size_m": {"width": 6.0, "height": 6.0},
    },
    {
        "id": "equipment",
        "label": "Equipment",
        "kind": "equipment",
        "role": "facility",
        "node_type": "facilityNode",
        "size_m": {"width": 4.0, "height": 3.0},
    },
    {
        "id": "shop",
        "label": "Shop",
        "kind": "shop",
        "role": "facility",
        "node_type": "facilityNode",
        "size_m": {"width": 6.0, "height": 4.0},
    },
    {
        "id": "obstacle",
        "label": "Obstacle",
        "kind": "obstacle",
        "role": "facility",
        "node_type": "facilityNode",
        "size_m": {"width": 5.0, "height": 4.0},
    },
)


def design_inspector_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/inspector.html"


def serve_design_inspector(host: str, port: int) -> None:
    handler = lambda *args, **kwargs: DesignInspectorHandler(  # noqa: E731
        *args,
        directory=str(ROOT),
        **kwargs,
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"[SANDBOX] design_inspector={design_inspector_url(host, port)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[SANDBOX] design inspector stopped")


def template_catalog_payload() -> dict[str, Any]:
    return {
        "default_template_id": DEFAULT_TEMPLATE_ID,
        "templates": [template.as_dict() for template in topology_templates()],
        "component_palette": list(COMPONENT_PALETTE),
        "reference_wheels": [
            {
                "name": "xyflow / React Flow",
                "repo": "https://github.com/xyflow/xyflow",
                "absorbed": [
                    "multi-handle nodes",
                    "connection validation",
                    "drag/drop canvas state",
                ],
            },
            {
                "name": "dagre",
                "repo": "https://github.com/dagrejs/dagre",
                "absorbed": [],
                "deferred": "automatic layout command",
            },
            {
                "name": "react-jsonschema-form",
                "repo": "https://github.com/rjsf-team/react-jsonschema-form",
                "absorbed": [],
                "deferred": "schema-driven property panel",
            },
        ],
    }


def build_design_payload(template_id: str) -> dict[str, Any]:
    return document_payload(create_design(template_id))


def compile_react_flow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = str(payload.get("template_id") or DEFAULT_TEMPLATE_ID)
    document = create_design(template_id)
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if isinstance(nodes, list):
        document = apply_react_flow_nodes(document, nodes)
    if isinstance(edges, list):
        document = apply_react_flow_edges(document, edges)
    return document_payload(document)


def document_payload(document) -> dict[str, Any]:
    flow = to_react_flow(document)
    validation_issues = [issue.as_dict() for issue in validate_design(document)]
    graph_payload = _compile_graph_payload(document)
    issue_counts = Counter(issue["severity"] for issue in validation_issues)
    graph_diagnostics = graph_payload.get("diagnostics", [])
    graph_counts = Counter(item["severity"] for item in graph_diagnostics)
    fallback_edges = int(graph_payload.get("origin_counts", {}).get("walkable_access_fallback", 0))
    inferred_endpoints = sum(
        1 for item in graph_diagnostics if item.get("code") == "graph.connection_endpoint_inferred"
    )

    return {
        "document": document.as_dict(),
        "react_flow": flow,
        "validation_issues": validation_issues,
        "graph": graph_payload,
        "summary": {
            "status": _summary_status(issue_counts, graph_counts, fallback_edges),
            "validation_errors": issue_counts.get("error", 0),
            "validation_warnings": issue_counts.get("warning", 0),
            "graph_errors": graph_counts.get("error", 0),
            "graph_warnings": graph_counts.get("warning", 0),
            "fallback_edges": fallback_edges,
            "inferred_endpoints": inferred_endpoints,
            "document_connections": len(document.connections),
        },
    }


def _compile_graph_payload(document) -> dict[str, Any]:
    try:
        graph = StationGraph.from_design(document)
    except Exception as exc:
        return {
            "node_count": 0,
            "edge_count": 0,
            "origin_counts": {},
            "connection_status": {},
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "graph.compile_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                    "connection_id": None,
                    "element_id": None,
                    "from_node": None,
                    "to_node": None,
                    "metadata": {},
                }
            ],
            "edges": [],
        }

    origin_counts = Counter(edge.origin for edge in graph.edges)
    connection_origins: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in graph.edges:
        if edge.detail_id:
            connection_origins[edge.detail_id][edge.origin] += 1

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "origin_counts": dict(sorted(origin_counts.items())),
        "connection_status": {
            connection_id: {
                "edge_count": sum(counter.values()),
                "origin_counts": dict(sorted(counter.items())),
            }
            for connection_id, counter in sorted(connection_origins.items())
        },
        "diagnostics": [diagnostic.as_dict() for diagnostic in graph.compile_diagnostics],
        "edges": [
            {
                "from": edge.from_node,
                "to": edge.to_node,
                "kind": edge.kind,
                "origin": edge.origin,
                "detail_id": edge.detail_id,
                "level_change": edge.level_change,
                "facility_stage": edge.facility_stage,
            }
            for edge in graph.edges
        ],
    }


def _summary_status(
    issue_counts: Counter[str],
    graph_counts: Counter[str],
    fallback_edges: int,
) -> str:
    if issue_counts.get("error", 0) or graph_counts.get("error", 0):
        return "error"
    if issue_counts.get("warning", 0) or graph_counts.get("warning", 0) or fallback_edges:
        return "warning"
    return "ok"


class DesignInspectorHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"", "/"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/inspector.html")
            self.end_headers()
            return
        if parsed.path == "/api/templates":
            self._send_json(template_catalog_payload())
            return
        if parsed.path == "/api/design":
            params = parse_qs(parsed.query)
            template_id = params.get("template", [DEFAULT_TEMPLATE_ID])[0]
            self._send_design(template_id)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/compile":
            self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        try:
            payload = self._read_json_body()
            self._send_json(compile_react_flow_payload(payload))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _send_design(self, template_id: str) -> None:
        try:
            self._send_json(build_design_payload(template_id))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
