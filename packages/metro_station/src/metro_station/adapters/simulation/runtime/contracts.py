from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SIMULATION_TRACE_SCHEMA_VERSION = "simulation_trace.v1"
VISUALIZATION_BUNDLE_SCHEMA_VERSION = "visualization_bundle.v1"
TRACK_POINT_SCHEMA = (
    "time",
    "x",
    "y",
    "heading",
    "size",
    "target_x",
    "target_y",
    "target_mode",
    "diagnostic",
    "meta",
)


@dataclass(frozen=True)
class SimulationTrace:
    run_id: str
    metadata: dict[str, Any]
    snapshots: list[dict[str, Any]]
    facility_events: list[dict[str, Any]]
    aggregate_metrics: dict[str, Any]
    movement_trace: dict[str, Any] = field(default_factory=dict)
    facility_motion_trace: dict[str, Any] = field(default_factory=dict)
    terminal_events: list[dict[str, Any]] = field(default_factory=list)
    routing_decision_logs: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SIMULATION_TRACE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "metadata": self.metadata,
            "snapshots": self.snapshots,
            "facility_events": self.facility_events,
            "movement_trace": self.movement_trace,
            "facility_motion_trace": self.facility_motion_trace,
            "aggregate_metrics": self.aggregate_metrics,
            "terminal_events": self.terminal_events,
            "routing_decision_logs": self.routing_decision_logs,
        }


@dataclass(frozen=True)
class VisualizationBundle:
    source_run_id: str
    visual_tracks: list[dict[str, Any]]
    visual_facility_animations: dict[str, Any]
    debug_layers: dict[str, Any] = field(default_factory=dict)
    schema_version: str = VISUALIZATION_BUNDLE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_run_id": self.source_run_id,
            "track_point_schema": list(TRACK_POINT_SCHEMA),
            "visual_tracks": self.visual_tracks,
            "visual_facility_animations": self.visual_facility_animations,
            "debug_layers": self.debug_layers,
        }


def track_point_meta(
    source: str,
    *,
    visual_only: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": source,
        "visual_only": bool(visual_only),
    }
    if reason:
        payload["reason"] = reason
    return payload


def diagnostic_truth_payload(tracks_payload: dict[str, Any]) -> dict[str, Any]:
    """Return a JPS_TRACKS-compatible payload with visual-only samples removed."""

    sanitized = dict(tracks_payload)
    agents = tracks_payload.get("agents")
    if not isinstance(agents, list):
        visual = tracks_payload.get("visualization_bundle")
        if isinstance(visual, dict):
            agents = visual.get("visual_tracks")
    if isinstance(agents, list):
        sanitized["agents"] = [
            diagnostic_agent(agent) for agent in agents if isinstance(agent, dict)
        ]

    visual = tracks_payload.get("visualization_bundle")
    if isinstance(visual, dict):
        sanitized_visual = dict(visual)
        visual_tracks = visual.get("visual_tracks")
        if isinstance(visual_tracks, list):
            sanitized_visual["visual_tracks"] = [
                diagnostic_agent(agent)
                for agent in visual_tracks
                if isinstance(agent, dict)
            ]
        sanitized["visualization_bundle"] = sanitized_visual
    return sanitized


def diagnostic_agent(agent: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(agent)
    sanitized.pop("presentation_points", None)
    points = agent.get("points")
    if not isinstance(points, list):
        return sanitized
    sanitized["points"] = [
        diagnostic_point(point)
        for point in points
        if is_diagnostic_point(point)
    ]
    return sanitized


def is_diagnostic_point(point: Any) -> bool:
    if not isinstance(point, list | tuple):
        return False
    if len(point) <= 9:
        return True
    meta = point[9]
    if not isinstance(meta, dict):
        return True
    return not bool(meta.get("visual_only"))


def diagnostic_point(point: Any) -> list[Any]:
    return list(point[:9]) if isinstance(point, list | tuple) else []
