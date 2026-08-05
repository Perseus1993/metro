from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from threading import Lock, Thread
from time import time
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from metro_station.adapters.simulation.design.react_flow_adapter import (
    apply_react_flow_edges,
    apply_react_flow_nodes,
    to_react_flow,
)
from metro_station.adapters.simulation.design.layout_rules import element_size_limits
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.templates import (
    create_design,
    scratch_topology_templates,
    topology_templates,
)
from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station_experiments.runner import ExperimentCase, ExperimentRunner
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station_visualizer.config import ASSET_DIR as VISUAL_ASSET_ROOT
from .analysis_case_api import (
    build_baseline_case,
    build_candidate_case,
    case_differences,
    import_case,
)
from .algorithm_api import (
    algorithm_catalog,
    import_experiment_plan,
    preflight_algorithm,
    register_algorithm,
    template_catalog,
)
from .comparison_jobs import (
    comparison_job_payload,
    comparison_job_report,
    record_decision,
    start_comparison_job,
)
from .comparison_report_export import comparison_report_bundle
from .control_plan_catalog import build_control_plan_catalog
from .demand_flows import compile_demand_flows, operations_with_demand_flows
from .debug_log import DESIGN_DEBUG_LOG
from .operations import default_operations, normalize_operations, operation_schema_payload


ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_ID = "scratch_single_level"
MAX_SIMULATION_JOBS = 20
MAX_JSON_BODY_BYTES = 10 * 1024 * 1024
PRODUCT_POST_PATHS = frozenset(
    {
        "/api/analysis-cases/baseline",
        "/api/analysis-cases/candidate",
        "/api/analysis-cases/diff",
        "/api/analysis-cases/import",
        "/api/comparisons",
        "/api/routing-algorithms/preflight",
        "/api/routing-algorithms/register",
        "/api/experiment-plans/import",
    }
)
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
    debug_session_id: str = "unknown"
    debug_request_id: str | None = None


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
        "label": "Platform L1 down",
        "kind": "platform_edge",
        "role": "facility",
        "node_type": "facilityNode",
        "direction": "down",
        "line_id": "L1",
        "size_m": {"width": 7.0, "height": 3.0},
    },
    {
        "id": "platform_edge_l2_up",
        "label": "Platform L2 up",
        "kind": "platform_edge",
        "role": "facility",
        "node_type": "facilityNode",
        "direction": "up",
        "line_id": "L2",
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
        "id": "up_escalator",
        "label": "Up escalator",
        "kind": "escalator",
        "role": "vertical_connector",
        "node_type": "verticalConnector",
        "direction": "up",
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
PASSENGER_FLOW_PALETTE = (
    {
        "id": "entry_flow",
        "label": "Entry → board",
        "intent": "enter_and_board",
        "source_kind": "entrance",
        "operation_id": "entry_count_hour",
        "default_rate_per_hour": 2000,
    },
    {
        "id": "exit_flow",
        "label": "Train → exit",
        "intent": "exit_station",
        "source_kind": "platform_edge",
        "operation_id": "exit_count_hour",
        "default_rate_per_hour": 1000,
    },
    {
        "id": "transfer_flow",
        "label": "Platform transfer",
        "intent": "transfer",
        "source_kind": "platform_edge",
        "operation_id": "transfer_count_hour",
        "default_rate_per_hour": 1000,
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
        "templates": [
            template.as_dict()
            for template in (*scratch_topology_templates(), *topology_templates())
        ],
        "component_palette": [
            {
                **component,
                "size_limits_m": limits.as_dict() if limits is not None else None,
            }
            for component in COMPONENT_PALETTE
            for limits in (element_size_limits(str(component["kind"])),)
        ],
        "passenger_flow_palette": [dict(flow) for flow in PASSENGER_FLOW_PALETTE],
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
    raw_operations = (
        dict(payload["operations"]) if isinstance(payload.get("operations"), dict) else {}
    )
    for field_id in default_operations():
        if payload.get(field_id) is not None:
            raw_operations[field_id] = payload[field_id]
    operations = normalize_operations(raw_operations)
    nodes = _object_list(payload, "nodes")
    edges = _object_list(payload, "edges")
    if nodes is not None:
        document = apply_react_flow_nodes(document, nodes)
    if edges is not None:
        document = apply_react_flow_edges(document, edges)
    generation_issues: list[dict[str, str]] = []
    if payload.get("generate_station") is True:
        try:
            document = generate_station(document)
        except ValueError as exc:
            # A scratch layout may be syntactically valid while leaving no
            # body-sized queue domain around one of its facilities.  This is a
            # design validation result, not a malformed API request: keep the
            # edited document available to the inspector and report the
            # generation failure through the normal deterministic issue path.
            raw_message = str(exc)
            code, separator, detail = raw_message.partition(":")
            if not separator or "." not in code:
                code = "spatial_capacity.queue_domain_unavailable"
                detail = raw_message
            generation_issues.append(
                {
                    "severity": "error",
                    "code": code,
                    "path": "queues",
                    "message": detail.strip(),
                }
            )
    demand_flows, demand_issues = compile_demand_flows(nodes or [], document)
    operations = normalize_operations(
        operations_with_demand_flows(
            operations,
            demand_flows,
            zero_unspecified=bool(document.metadata.get("editor_scratch")),
        )
    )
    return document_payload(
        document,
        operations=operations,
        demand_flows=demand_flows,
        extra_validation_issues=[*generation_issues, *demand_issues],
    )


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
            entry_count_hour=_simulate_int(operations, "entry_count_hour", 4000),
            exit_count_hour=_simulate_int(operations, "exit_count_hour", 2000),
            transfer_count_hour=_simulate_int(operations, "transfer_count_hour", 0),
            seed=_simulation_control_int(payload, "seed", 42, minimum=0, maximum=2**31 - 1),
            minutes=_simulate_int(operations, "minutes", 1),
            tick_seconds=_simulation_control_int(
                payload,
                "tick_seconds",
                5,
                minimum=1,
                maximum=60,
            ),
            group_size=_simulate_int(operations, "group_size", 1),
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
            result.trajectory_report.as_dict() if result.trajectory_report is not None else None
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


def start_simulation_job(
    payload: dict[str, Any],
    *,
    debug_session_id: str = "unknown",
    debug_request_id: str | None = None,
) -> dict[str, Any]:
    compiled = compile_react_flow_payload(payload)
    summary = compiled.get("summary", {})
    if summary.get("status") == "error":
        return {
            "status": "error",
            "metrics": {},
            "trajectory_report": None,
            "error": "Simulation blocked: fix layout validation or graph errors first.",
            "compile_summary": summary,
            "validation_issues": compiled.get("validation_issues", []),
            "graph_diagnostics": compiled.get("graph", {}).get("diagnostics", []),
        }

    job = SimulationJob(
        job_id=uuid4().hex,
        debug_session_id=debug_session_id,
        debug_request_id=debug_request_id,
    )
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
    with _SIMULATION_LOCK:
        debug_job = _SIMULATION_JOBS.get(job_id)
        debug_session_id = debug_job.debug_session_id if debug_job else "unknown"
        debug_request_id = debug_job.debug_request_id if debug_job else None
    DESIGN_DEBUG_LOG.record(
        "simulation.completed",
        source="server",
        session_id=debug_session_id,
        request_id=debug_request_id,
        status="error" if result.get("status") == "error" else "ok",
        details={"job_id": job_id, "result": result},
    )
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


def document_payload(
    document,
    *,
    operations: Any = None,
    demand_flows: list[dict[str, Any]] | None = None,
    extra_validation_issues: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    normalized_operations = normalize_operations(operations)
    flow = to_react_flow(document)
    validation_issues = [issue.as_dict() for issue in validate_station_design(document)]
    validation_issues.extend(extra_validation_issues or [])
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
        "control_catalog": build_control_plan_catalog(document, normalized_operations),
        "demand_flows": demand_flows or [],
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


def _simulate_int(operations: dict[str, int | float], key: str, default: int) -> int:
    if key in operations:
        return max(0, int(float(operations[key])))
    return default


def _simulation_control_int(
    payload: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = float(payload.get(key, default))
    except (TypeError, ValueError):
        value = float(default)
    if not isfinite(value):
        value = float(default)
    return max(minimum, min(maximum, int(value)))


def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"every {key} item must be an object")
    return value


def _compile_debug_result(
    result: dict[str, Any],
    *,
    include_snapshot: bool,
) -> dict[str, Any]:
    details = {
        "summary": result.get("summary", {}),
        "validation_issues": result.get("validation_issues", []),
        "graph_diagnostics": result.get("graph", {}).get("diagnostics", []),
        "operations": result.get("operations", {}),
        "demand_flows": result.get("demand_flows", []),
    }
    if include_snapshot:
        details["generated_snapshot"] = result
    return details


def _query_int(
    params: dict[str, list[str]],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(params.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


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
        if parsed.path == "/api/routing-algorithms":
            self._send_json(algorithm_catalog())
            return
        if parsed.path == "/api/experiment-templates":
            self._send_json(template_catalog())
            return
        if parsed.path == "/api/design":
            params = parse_qs(parsed.query)
            template_id = params.get("template", [DEFAULT_TEMPLATE_ID])[0]
            self._send_design(template_id)
            return
        if parsed.path == "/api/debug/events":
            params = parse_qs(parsed.query)
            limit = _query_int(params, "limit", 100, minimum=1, maximum=2_000)
            session_id = params.get("session_id", [""])[0]
            self._send_json(
                {
                    "events": DESIGN_DEBUG_LOG.read(
                        limit=limit,
                        session_id=session_id or None,
                    ),
                    "log_path": str(DESIGN_DEBUG_LOG.path.resolve()),
                }
            )
            return
        if parsed.path == "/api/debug/export":
            params = parse_qs(parsed.query)
            session_id = params.get("session_id", [""])[0]
            self._send_bytes(
                DESIGN_DEBUG_LOG.export_jsonl(session_id=session_id or None),
                content_type="application/x-ndjson; charset=utf-8",
                filename="station_designer_debug.jsonl",
            )
            return
        if parsed.path.startswith("/api/simulate/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            payload = simulation_job_payload(job_id)
            if payload is None:
                self._send_json({"error": "simulation job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/comparisons/jobs/"):
            self._send_comparison_job(parsed.path)
            return
        if parsed.path.startswith("/visual-assets/"):
            self._send_visual_asset(parsed.path.removeprefix("/visual-assets/"))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        is_decision = parsed.path.endswith("/decision") and parsed.path.startswith(
            "/api/comparisons/jobs/"
        )
        if (
            parsed.path
            not in {
                "/api/compile",
                "/api/simulate",
                "/api/debug/events",
                *PRODUCT_POST_PATHS,
            }
            and not is_decision
        ):
            self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        request_id = uuid4().hex
        session_id = self._debug_session_id()
        try:
            payload = self._read_json_body()
            if parsed.path in PRODUCT_POST_PATHS or is_decision:
                self._handle_product_post(parsed.path, payload)
                return
            if parsed.path == "/api/debug/events":
                event = self._record_client_event(payload, session_id=session_id)
                self._send_json({"accepted": True, "event": event}, status=HTTPStatus.CREATED)
                return
            if parsed.path == "/api/simulate":
                DESIGN_DEBUG_LOG.record(
                    "simulation.requested",
                    source="server",
                    session_id=session_id,
                    request_id=request_id,
                    details={"payload": payload},
                )
                result = start_simulation_job(
                    payload,
                    debug_session_id=session_id,
                    debug_request_id=request_id,
                )
                DESIGN_DEBUG_LOG.record(
                    "simulation.queued" if result.get("job_id") else "simulation.blocked",
                    source="server",
                    session_id=session_id,
                    request_id=request_id,
                    status="ok" if result.get("job_id") else "error",
                    details={"result": result},
                )
                status = (
                    HTTPStatus.ACCEPTED if result.get("job_id") else HTTPStatus.UNPROCESSABLE_ENTITY
                )
                self._send_json(result, status=status)
                return
            DESIGN_DEBUG_LOG.record(
                "station.generate_requested"
                if payload.get("generate_station") is True
                else "design.compile_requested",
                source="server",
                session_id=session_id,
                request_id=request_id,
                details={"payload": payload},
            )
            result = compile_react_flow_payload(payload)
            generated = payload.get("generate_station") is True
            DESIGN_DEBUG_LOG.record(
                "station.generated" if generated else "design.compiled",
                source="server",
                session_id=session_id,
                request_id=request_id,
                status="error" if result.get("summary", {}).get("status") == "error" else "ok",
                details=_compile_debug_result(result, include_snapshot=generated),
            )
            self._send_json(result)
        except RequestBodyTooLarge as exc:
            self._record_request_failure(parsed.path, session_id, request_id, exc)
            self._send_json({"error": str(exc)}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except ValueError as exc:
            self._record_request_failure(parsed.path, session_id, request_id, exc)
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._record_request_failure(parsed.path, session_id, request_id, exc)
            self._send_json(
                {"error": "internal server error", "detail": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_product_post(self, path: str, payload: dict[str, Any]) -> None:
        if path == "/api/analysis-cases/import":
            self._send_json({"case": import_case(payload).as_dict()})
            return
        if path == "/api/analysis-cases/diff":
            self._send_json({"differences": case_differences(payload)})
            return
        if path == "/api/analysis-cases/baseline":
            compiled = compile_react_flow_payload(payload)
            case = build_baseline_case(payload, compiled)
            self._send_json({"case": case.as_dict()}, status=HTTPStatus.CREATED)
            return
        if path == "/api/analysis-cases/candidate":
            compiled = compile_react_flow_payload(payload)
            case = build_candidate_case(payload, compiled)
            differences = case_differences(
                {"baseline": payload.get("baseline"), "candidate": case.as_dict()}
            )
            self._send_json(
                {"case": case.as_dict(), "differences": differences},
                status=HTTPStatus.CREATED,
            )
            return
        if path == "/api/comparisons":
            self._send_json(start_comparison_job(payload), status=HTTPStatus.ACCEPTED)
            return
        if path == "/api/routing-algorithms/preflight":
            self._send_json(preflight_algorithm(payload))
            return
        if path == "/api/routing-algorithms/register":
            self._send_json(register_algorithm(payload), status=HTTPStatus.CREATED)
            return
        if path == "/api/experiment-plans/import":
            self._send_json({"plan": import_experiment_plan(payload)})
            return
        job_id = path.split("/")[-2]
        result = record_decision(job_id, payload)
        if result is None:
            exists = comparison_job_payload(job_id) is not None
            status = HTTPStatus.CONFLICT if exists else HTTPStatus.NOT_FOUND
            self._send_json({"error": "comparison report is not ready"}, status=status)
            return
        self._send_json(result)

    def _send_comparison_job(self, path: str) -> None:
        parts = path.strip("/").split("/")
        job_id = parts[3] if len(parts) >= 4 else ""
        if path.endswith("/export"):
            report = comparison_job_report(job_id)
            if report is None:
                exists = comparison_job_payload(job_id) is not None
                status = HTTPStatus.CONFLICT if exists else HTTPStatus.NOT_FOUND
                self._send_json({"error": "comparison report is not ready"}, status=status)
                return
            self._send_bytes(
                comparison_report_bundle(report),
                content_type="application/zip",
                filename=f"comparison-{report.spec.experiment_id}.zip",
            )
            return
        payload = comparison_job_payload(job_id)
        if payload is None:
            self._send_json({"error": "comparison job not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(payload)

    def _send_design(self, template_id: str) -> None:
        try:
            result = build_design_payload(template_id)
            DESIGN_DEBUG_LOG.record(
                "design.loaded",
                source="server",
                session_id=self._debug_session_id(),
                status="ok",
                details={"template_id": template_id, "summary": result.get("summary", {})},
            )
            self._send_json(result)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)

    def _send_visual_asset(self, asset_name: str) -> None:
        candidate = (VISUAL_ASSET_ROOT / asset_name).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(VISUAL_ASSET_ROOT):
            self.send_error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", self.guess_type(str(candidate)))
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.end_headers()
        with candidate.open("rb") as source:
            self.wfile.write(source.read())

    def _read_json_body(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if content_length <= 0:
            return {}
        if content_length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge(f"JSON body exceeds {MAX_JSON_BODY_BYTES} byte limit")
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

    def _send_bytes(self, body: bytes, *, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _debug_session_id(self) -> str:
        return str(self.headers.get("X-Debug-Session") or "unknown")[:128]

    def _record_client_event(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        if not action:
            raise ValueError("debug action is required")
        details = payload.get("details")
        if details is not None and not isinstance(details, dict):
            raise ValueError("debug details must be an object")
        return DESIGN_DEBUG_LOG.record(
            action,
            source="client",
            session_id=session_id,
            status=str(payload.get("status") or "info"),
            details=details or {},
            client_sequence=payload.get("sequence"),
        )

    @staticmethod
    def _record_request_failure(
        path: str,
        session_id: str,
        request_id: str,
        exc: Exception,
    ) -> None:
        DESIGN_DEBUG_LOG.record(
            "request.failed",
            source="server",
            session_id=session_id,
            request_id=request_id,
            status="error",
            details={"path": path, "error_type": type(exc).__name__, "error": str(exc)},
        )
