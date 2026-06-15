from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from time import time
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ..design.react_flow_adapter import (
    apply_react_flow_edges,
    apply_react_flow_nodes,
    to_react_flow,
)
from ..design.schema import StationDesignDocument
from ..design.templates import create_design, topology_templates
from ..design.validation import validate_design
from ..experiment.runner import ExperimentCase, ExperimentRunner
from ..station.graph import StationGraph
from .operations import default_operations, normalize_operations, operation_schema_payload


ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_ID = "visual_demo_station"
MAX_SIMULATION_JOBS = 20
MAX_JSON_BODY_BYTES = 10 * 1024 * 1024
_SIMULATION_LOCK = Lock()
_SIMULATION_JOBS: dict[str, "SimulationJob"] = {}


class RequestBodyTooLarge(ValueError):
    pass


@dataclass
class SimulationJob:
    job_id: str
    status: str = "queued"
    step: int = 0
    total_steps: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
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
        "operations_schema": operation_schema_payload(),
        "default_operations": default_operations(),
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
    operations = normalize_operations(payload.get("operations"))
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if isinstance(nodes, list):
        document = apply_react_flow_nodes(document, nodes)
    if isinstance(edges, list):
        document = apply_react_flow_edges(document, edges)
    return document_payload(document, operations=operations)


def simulate_design_payload(
    payload: dict[str, Any],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    try:
        compiled = compile_react_flow_payload(payload)
        summary = compiled.get("summary", {})
        if summary.get("status") == "error":
            return {
                "status": "error",
                "metrics": {},
                "trajectory_report": None,
                "error": "Design compile failed; fix validation or graph errors first.",
                "compile_summary": summary,
            }

        document = StationDesignDocument.from_dict(compiled["document"])
        operations = normalize_operations(compiled.get("operations"))
        case = ExperimentCase(
            case_id="inspector_preview",
            design=document,
            design_label=str(payload.get("template_id") or DEFAULT_TEMPLATE_ID),
            entry_count_hour=_simulate_int(payload, operations, "entry_count_hour", 4000),
            exit_count_hour=_simulate_int(payload, operations, "exit_count_hour", 2000),
            seed=_simulate_int(payload, operations, "seed", 42),
            minutes=_simulate_int(payload, operations, "minutes", 1),
            tick_seconds=_simulate_int(payload, operations, "tick_seconds", 5),
            group_size=_simulate_int(payload, operations, "group_size", 1),
            movement_backend=str(payload.get("movement_backend") or "batched_jupedsim"),
            jupedsim_model=str(payload.get("jupedsim_model") or "collision_free_speed"),
            station_name="inspector_preview",
            operations=operations,
        )
        result = ExperimentRunner([case]).run_case(
            case,
            progress_callback=progress_callback,
        )
        trajectory = (
            result.trajectory_report.as_dict()
            if result.trajectory_report is not None
            else None
        )
        return {
            "status": result.status,
            "metrics": _simulate_metrics(result.metrics, result.tracks_payload, trajectory),
            "trajectory_report": trajectory,
            "error": result.error,
            "compile_summary": summary,
        }
    except Exception as exc:
        return {
            "status": "error",
            "metrics": {},
            "trajectory_report": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def start_simulation_job(payload: dict[str, Any]) -> dict[str, Any]:
    job = SimulationJob(job_id=uuid4().hex)
    with _SIMULATION_LOCK:
        _SIMULATION_JOBS[job.job_id] = job
        _trim_simulation_jobs_locked()

    worker = Thread(
        target=_run_simulation_job,
        args=(job.job_id, payload),
        name=f"simulation-job-{job.job_id[:8]}",
        daemon=True,
    )
    worker.start()
    return _simulation_job_payload(job)


def simulation_job_payload(job_id: str) -> dict[str, Any] | None:
    with _SIMULATION_LOCK:
        job = _SIMULATION_JOBS.get(job_id)
        if job is None:
            return None
        return _simulation_job_payload(job)


def _run_simulation_job(job_id: str, payload: dict[str, Any]) -> None:
    _update_simulation_job(job_id, status="running", step=0, total_steps=0)

    def report_progress(step: int, total_steps: int) -> None:
        _update_simulation_job(
            job_id,
            step=max(0, int(step)),
            total_steps=max(0, int(total_steps)),
        )

    result = simulate_design_payload(payload, progress_callback=report_progress)
    if result.get("status") == "error":
        _update_simulation_job(
            job_id,
            status="error",
            result=result,
            error=str(result.get("error") or "Simulation failed"),
        )
        return
    _update_simulation_job(job_id, status="done", result=result)


def _update_simulation_job(job_id: str, **changes: Any) -> None:
    with _SIMULATION_LOCK:
        job = _SIMULATION_JOBS.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time()


def _simulation_job_payload(job: SimulationJob) -> dict[str, Any]:
    progress = 0.0
    if job.total_steps > 0:
        progress = max(0.0, min(1.0, job.step / job.total_steps))
    return {
        "job_id": job.job_id,
        "status": job.status,
        "step": job.step,
        "total_steps": job.total_steps,
        "progress": progress,
        "result": job.result,
        "error": job.error,
    }


def _trim_simulation_jobs_locked() -> None:
    if len(_SIMULATION_JOBS) <= MAX_SIMULATION_JOBS:
        return
    ordered = sorted(_SIMULATION_JOBS.values(), key=lambda job: job.created_at)
    for job in ordered[: len(_SIMULATION_JOBS) - MAX_SIMULATION_JOBS]:
        if job.status in {"queued", "running"}:
            continue
        _SIMULATION_JOBS.pop(job.job_id, None)


def document_payload(document, *, operations: Any = None) -> dict[str, Any]:
    normalized_operations = normalize_operations(operations)
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
        "operations": normalized_operations,
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


def _simulate_int(
    payload: dict[str, Any],
    operations: dict[str, int | float],
    key: str,
    default: int,
) -> int:
    raw_operations = payload.get("operations") if isinstance(payload.get("operations"), dict) else {}
    if payload.get(key) is not None:
        return max(0, int(float(payload[key])))
    if key in raw_operations:
        return max(0, int(float(raw_operations[key])))
    if key in operations:
        return max(0, int(float(operations[key])))
    return default


def _simulate_metrics(
    metrics: dict[str, Any],
    tracks_payload: dict[str, Any] | None,
    trajectory: dict[str, Any] | None,
) -> dict[str, Any]:
    response = dict(metrics or {})
    clearance = tracks_payload.get("clearance_audit") if tracks_payload else None
    if isinstance(clearance, dict):
        response["remaining_agents"] = int(clearance.get("remaining_agents", 0) or 0)
        response["completed_agents"] = int(clearance.get("completed_agents", 0) or 0)
        response["total_agents"] = int(clearance.get("total_agents", 0) or 0)
    if trajectory:
        response["completion_rate"] = trajectory.get("completion_rate", 0.0)
        response["trajectory_pass_fail"] = trajectory.get("pass_fail")
        response["stuck_agents"] = trajectory.get("stuck_agents", 0)
    return response


class DesignInspectorHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

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
        if parsed.path.startswith("/api/simulate/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            payload = simulation_job_payload(job_id)
            if payload is None:
                self._send_json({"error": "simulation job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/compile", "/api/simulate"}:
            self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        try:
            payload = self._read_json_body()
            if parsed.path == "/api/simulate":
                self._send_json(start_simulation_job(payload), status=HTTPStatus.ACCEPTED)
                return
            self._send_json(compile_react_flow_payload(payload))
        except RequestBodyTooLarge as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json(
                {"error": "internal server error", "detail": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _send_design(self, template_id: str) -> None:
        try:
            self._send_json(build_design_payload(template_id))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)

    def _read_json_body(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if content_length <= 0:
            return {}
        if content_length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge(
                f"JSON body exceeds {MAX_JSON_BODY_BYTES} byte limit"
            )
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
        self.end_headers()
        self.wfile.write(body)
