from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from metro_alignment.datasets.registry import PORTABLE_DATASET_ID, is_portable_basename

SceneStatus = Literal["ready", "pending"]
GeometryEvidenceStatus = Literal["proxy", "observed_matched"]


@dataclass(frozen=True)
class SceneConfig:
    scene_id: str
    status: SceneStatus
    minutes: int
    tick_seconds: int = 1
    entry_count_hour: int = 1000
    exit_count_hour: int = 0
    demand_minutes: int = 1
    movement_trace_sample_seconds: float = 0.2
    entry_entrance_weights: tuple[tuple[str, float], ...] = ()
    jupedsim_dt_seconds: float = 0.01
    jupedsim_iterations_per_tick: int = 150
    jupedsim_desired_speed_mps: float = 1.2
    jupedsim_free_speed_min_mps: float = 0.75
    jupedsim_free_speed_max_mps: float = 1.65
    stairs_preference_share: float = 0.18
    stair_fatigue_cost_up: float = 0.6
    stair_fatigue_cost_down: float = 0.15
    stair_bidirectional_conflict_factor: float = 0.3
    gate_service_persons_per_min: int = 55
    entry_admission_residence_seconds: float | None = None
    entry_admission_residence_percentile: str | None = None
    entry_admission_residence_evidence_ref: str | None = None
    exit_admission_residence_seconds: float | None = None
    exit_admission_residence_percentile: str | None = None
    exit_admission_residence_evidence_ref: str | None = None
    entry_admission_burst_sigma: float = 3.0
    entry_admission_token_capacity: int | None = None
    exit_admission_token_capacity: int | None = None
    train_dwell_seconds: float = 60.0
    escalator_speed_units_per_tick: float = 2.3
    stairs_speed_units_per_tick: float = 1.55
    elevator_speed_units_per_tick: float = 4.2
    seed: int = 42
    observed_dataset_id: str | None = None
    measurement_bounds_m: tuple[float, float, float, float] | None = None
    measurement_area_id: str | None = None
    comparison_frame_id: str | None = None
    coordinate_transform_id: str | None = None
    coordinate_translation_m: tuple[float, float] | None = None
    pending_reason: str = ""
    geometry_evidence_status: GeometryEvidenceStatus = "proxy"
    geometry_evidence: str = "geometry has not been matched to an observation source"
    geometry_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scene_id, str)
            or PORTABLE_DATASET_ID.fullmatch(self.scene_id) is None
            or not is_portable_basename(self.scene_id)
        ):
            raise ValueError("scene_id must be a lowercase portable slug")
        if self.status not in {"ready", "pending"}:
            raise ValueError("scene status must be ready or pending")
        for name in ("minutes", "tick_seconds", "demand_minutes", "jupedsim_iterations_per_tick"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.demand_minutes > self.minutes:
            raise ValueError("demand_minutes must not exceed the simulation horizon minutes")
        for name in ("entry_count_hour", "exit_count_hour", "seed"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            not isinstance(self.gate_service_persons_per_min, int)
            or isinstance(self.gate_service_persons_per_min, bool)
            or self.gate_service_persons_per_min <= 0
        ):
            raise ValueError("gate_service_persons_per_min must be a positive integer")
        for name in (
            "movement_trace_sample_seconds",
            "jupedsim_dt_seconds",
            "jupedsim_desired_speed_mps",
            "jupedsim_free_speed_min_mps",
            "jupedsim_free_speed_max_mps",
            "train_dwell_seconds",
            "escalator_speed_units_per_tick",
            "stairs_speed_units_per_tick",
            "elevator_speed_units_per_tick",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f"{name} must be finite and > 0")
        for name in (
            "entry_admission_residence_seconds",
            "exit_admission_residence_seconds",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f"{name} must be finite and > 0 when provided")
        for name in (
            "entry_admission_residence_percentile",
            "exit_admission_residence_percentile",
        ):
            value = getattr(self, name)
            if value is not None and value not in {"p90", "p99"}:
                raise ValueError(f"{name} must be p90 or p99 when provided")
        for name in (
            "entry_admission_residence_evidence_ref",
            "exit_admission_residence_evidence_ref",
        ):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must be non-empty when provided")
        if (
            not isinstance(self.entry_admission_burst_sigma, (int, float))
            or isinstance(self.entry_admission_burst_sigma, bool)
            or not isfinite(self.entry_admission_burst_sigma)
            or self.entry_admission_burst_sigma < 0.0
        ):
            raise ValueError(
                "entry_admission_burst_sigma must be finite and non-negative"
            )
        for name in (
            "entry_admission_token_capacity",
            "exit_admission_token_capacity",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "stairs_preference_share",
            "stair_fatigue_cost_up",
            "stair_fatigue_cost_down",
            "stair_bidirectional_conflict_factor",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if self.jupedsim_free_speed_min_mps > self.jupedsim_free_speed_max_mps:
            raise ValueError("free-speed minimum must not exceed maximum")
        ratio = self.movement_trace_sample_seconds / self.jupedsim_dt_seconds
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError("movement trace interval must be an integer multiple of JuPedSim dt")
        if not isinstance(self.pending_reason, str):
            raise TypeError("pending_reason must be a string")
        if self.status == "pending" and not self.pending_reason.strip():
            raise ValueError("pending scenes require pending_reason")
        if self.measurement_bounds_m is not None and (
            not isinstance(self.measurement_bounds_m, tuple)
            or len(self.measurement_bounds_m) != 4
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                for value in self.measurement_bounds_m
            )
        ):
            raise ValueError("measurement_bounds_m must contain four finite numbers")
        if self.coordinate_translation_m is not None and (
            not isinstance(self.coordinate_translation_m, tuple)
            or len(self.coordinate_translation_m) != 2
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                for value in self.coordinate_translation_m
            )
        ):
            raise ValueError("coordinate_translation_m must contain two finite numbers")
        if self.status == "ready" and self.measurement_bounds_m is None:
            raise ValueError("ready scenes require explicit measurement_bounds_m")
        if self.status == "ready" and not (self.observed_dataset_id or "").strip():
            raise ValueError("ready scenes require an observed_dataset_id")
        if self.status == "ready" and any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.measurement_area_id,
                self.comparison_frame_id,
                self.coordinate_transform_id,
            )
        ):
            raise ValueError("ready scenes require a complete measurement transform contract")
        if self.status == "ready" and self.coordinate_translation_m is None:
            raise ValueError("ready scenes require a complete measurement transform contract")
        if not isinstance(self.geometry_evidence, str) or (
            self.status == "ready" and not self.geometry_evidence.strip()
        ):
            raise ValueError("ready scenes require explicit geometry evidence")
        if self.geometry_evidence_status not in {"proxy", "observed_matched"}:
            raise ValueError("geometry_evidence_status must be proxy or observed_matched")
        if self.geometry_evidence_status == "observed_matched" and (
            self.geometry_evidence_sha256 is None
            or len(self.geometry_evidence_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.geometry_evidence_sha256
            )
        ):
            raise ValueError("observed-matched geometry requires a lowercase SHA-256 evidence hash")
        if self.geometry_evidence_status == "proxy" and self.geometry_evidence_sha256 is not None:
            raise ValueError("proxy geometry must not carry an observed evidence hash")
