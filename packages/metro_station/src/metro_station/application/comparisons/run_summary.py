"""Run-level simulation and routing evidence contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping


RUN_SUMMARY_SCHEMA_VERSION = "run-summary/v1"


@dataclass(frozen=True)
class RunSummary:
    role: str
    case_id: str
    seed: int
    status: str
    cleared: bool
    right_censored: bool
    clearance_time_s: float | None
    remaining_agents: int
    total_agents: int
    peak_density_persons_m2: float
    density_exposure_person_s: float
    density_duration_above_threshold_s: float
    max_gate_queue: int
    max_vertical_queue: int
    stuck_agents: int
    peak_density_location: dict[str, Any] = field(default_factory=dict)
    top_bottleneck: dict[str, Any] | None = None
    control_events: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    algorithm_id: str | None = None
    algorithm_version: str | None = None
    algorithm_parameters: dict[str, Any] = field(default_factory=dict)
    paired_input_fingerprint: str | None = None
    simulation_duration_ms: float = 0.0
    routing_compute_duration_ms: float = 0.0
    routing_decision_logs: tuple[dict[str, Any], ...] = ()
    schema_version: str = RUN_SUMMARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_SUMMARY_SCHEMA_VERSION:
            raise ValueError(f"unsupported run-summary schema: {self.schema_version!r}")
        if self.role not in {"baseline", "candidate"}:
            raise ValueError("role must be baseline or candidate")
        if self.status not in {"ok", "error"}:
            raise ValueError("status must be ok or error")
        if self.status == "error" and not self.error:
            raise ValueError("error summaries require an error message")
        identity = (self.algorithm_id, self.algorithm_version, self.paired_input_fingerprint)
        if any(item is not None for item in identity) and not all(identity):
            raise ValueError("algorithm runs require id, version, and paired input fingerprint")
        for name, value in (
            ("simulation_duration_ms", self.simulation_duration_ms),
            ("routing_compute_duration_ms", self.routing_compute_duration_ms),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and >= 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "case_id": self.case_id,
            "seed": self.seed,
            "status": self.status,
            "cleared": self.cleared,
            "right_censored": self.right_censored,
            "clearance_time_s": self.clearance_time_s,
            "remaining_agents": self.remaining_agents,
            "total_agents": self.total_agents,
            "peak_density_persons_m2": self.peak_density_persons_m2,
            "density_exposure_person_s": self.density_exposure_person_s,
            "density_duration_above_threshold_s": self.density_duration_above_threshold_s,
            "max_gate_queue": self.max_gate_queue,
            "max_vertical_queue": self.max_vertical_queue,
            "stuck_agents": self.stuck_agents,
            "peak_density_location": dict(self.peak_density_location),
            "top_bottleneck": None if self.top_bottleneck is None else dict(self.top_bottleneck),
            "control_events": [dict(event) for event in self.control_events],
            "error": self.error,
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "algorithm_parameters": dict(self.algorithm_parameters),
            "paired_input_fingerprint": self.paired_input_fingerprint,
            "simulation_duration_ms": round(self.simulation_duration_ms, 6),
            "routing_compute_duration_ms": round(self.routing_compute_duration_ms, 6),
            "routing_decision_logs": [dict(log) for log in self.routing_decision_logs],
        }

    @classmethod
    def failed(
        cls,
        *,
        role: str,
        case_id: str,
        seed: int,
        error: str,
        algorithm_id: str | None = None,
        algorithm_version: str | None = None,
        algorithm_parameters: Mapping[str, Any] | None = None,
        paired_input_fingerprint: str | None = None,
        simulation_duration_ms: float = 0.0,
        routing_compute_duration_ms: float = 0.0,
        routing_decision_logs: tuple[dict[str, Any], ...] = (),
    ) -> RunSummary:
        return cls(
            role=role,
            case_id=case_id,
            seed=seed,
            status="error",
            cleared=False,
            right_censored=False,
            clearance_time_s=None,
            remaining_agents=0,
            total_agents=0,
            peak_density_persons_m2=0.0,
            density_exposure_person_s=0.0,
            density_duration_above_threshold_s=0.0,
            max_gate_queue=0,
            max_vertical_queue=0,
            stuck_agents=0,
            error=error,
            algorithm_id=algorithm_id,
            algorithm_version=algorithm_version,
            algorithm_parameters=dict(algorithm_parameters or {}),
            paired_input_fingerprint=paired_input_fingerprint,
            simulation_duration_ms=simulation_duration_ms,
            routing_compute_duration_ms=routing_compute_duration_ms,
            routing_decision_logs=routing_decision_logs,
        )
