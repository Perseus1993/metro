from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from math import ceil, isfinite
from typing import Any, Literal

import pandas as pd
from pydantic import Field, model_validator

from .formal_contract import ArtifactRecord, RuntimeCohort, StrictContract, canonical_sha256
from .formal_profiles import SaturatedFlowRegistration

SATURATED_FLOW_SCHEMA_VERSION = "alignment_saturated_flow.v1"


class SaturatedFlowArtifact(StrictContract):
    schema_version: Literal["alignment_saturated_flow.v1"]
    scene_id: str
    control_id: str
    registration: dict[str, Any]
    registration_sha256: str
    runtime_cohort: RuntimeCohort
    source_movement_trace: ArtifactRecord
    crossing_count: int = Field(ge=0)
    window_duration_s: float = Field(gt=0.0)
    active_bin_count: int = Field(ge=0)
    total_bin_count: int = Field(gt=0)
    active_bin_fraction: float = Field(ge=0.0, le=1.0)
    specific_flow_p_m_s: float = Field(ge=0.0)
    gate_status: Literal["pass", "fail"]
    release_eligible_for_step5: bool

    @model_validator(mode="after")
    def require_derived_gate_consistency(self) -> SaturatedFlowArtifact:
        low = float(self.registration["minimum_specific_flow_p_m_s"])
        high = float(self.registration["maximum_specific_flow_p_m_s"])
        minimum_active = float(self.registration["minimum_active_bin_fraction"])
        expected_pass = (
            low <= self.specific_flow_p_m_s <= high
            and self.active_bin_fraction >= minimum_active
        )
        if (self.gate_status == "pass") != expected_pass:
            raise ValueError("saturated-flow verdict contradicts its preregistered gate")
        if self.release_eligible_for_step5 != expected_pass:
            raise ValueError("saturated-flow release flag contradicts its gate")
        if canonical_sha256(self.registration) != self.registration_sha256:
            raise ValueError("saturated-flow registration hash is inconsistent")
        return self


def directed_crossing_times(
    trajectory: pd.DataFrame,
    registration: SaturatedFlowRegistration,
) -> tuple[float, ...]:
    required = {"agent_id", "t_s", "x_m", "y_m"}
    if not required.issubset(trajectory.columns):
        raise ValueError(f"trajectory is missing saturated-flow columns: {sorted(required)}")
    start = registration.line_start_m
    end = registration.line_end_m
    line_dx = end[0] - start[0]
    line_dy = end[1] - start[1]
    length_squared = line_dx * line_dx + line_dy * line_dy
    if length_squared <= 0.0:
        raise ValueError("measurement line must have positive length")

    crossings: list[float] = []
    ordered = trajectory.sort_values(["agent_id", "t_s"], kind="mergesort")
    for _, samples in ordered.groupby("agent_id", sort=False):
        rows = tuple(samples[["t_s", "x_m", "y_m"]].itertuples(index=False, name=None))
        for previous, current in pairwise(rows):
            crossing_time = _directed_segment_crossing(
                previous,
                current,
                start=start,
                line_dx=line_dx,
                line_dy=line_dy,
                length_squared=length_squared,
            )
            if crossing_time is None:
                continue
            if registration.window_start_s <= crossing_time <= registration.window_end_s:
                crossings.append(crossing_time)
    return tuple(sorted(crossings))


def _directed_segment_crossing(
    previous: tuple[float, float, float],
    current: tuple[float, float, float],
    *,
    start: tuple[float, float],
    line_dx: float,
    line_dy: float,
    length_squared: float,
) -> float | None:
    previous_t, previous_x, previous_y = (float(value) for value in previous)
    current_t, current_x, current_y = (float(value) for value in current)
    if current_t <= previous_t:
        raise ValueError("saturated-flow trajectories require strictly increasing time")
    values = (previous_t, previous_x, previous_y, current_t, current_x, current_y)
    if not all(isfinite(value) for value in values):
        raise ValueError("saturated-flow trajectories require finite physical values")
    previous_side = line_dx * (previous_y - start[1]) - line_dy * (previous_x - start[0])
    current_side = line_dx * (current_y - start[1]) - line_dy * (current_x - start[0])
    epsilon = 1e-12
    if previous_side >= -epsilon or current_side < -epsilon:
        return None
    alpha = -previous_side / (current_side - previous_side)
    crossing_x = previous_x + alpha * (current_x - previous_x)
    crossing_y = previous_y + alpha * (current_y - previous_y)
    projection = (
        (crossing_x - start[0]) * line_dx + (crossing_y - start[1]) * line_dy
    ) / length_squared
    if projection < -epsilon or projection > 1.0 + epsilon:
        return None
    return previous_t + alpha * (current_t - previous_t)


def evaluate_crossing_times(
    crossing_times: Iterable[float],
    registration: SaturatedFlowRegistration,
) -> dict[str, int | float | str | bool]:
    times = tuple(float(value) for value in crossing_times)
    if any(
        not isfinite(value)
        or value < registration.window_start_s
        or value > registration.window_end_s
        for value in times
    ):
        raise ValueError("crossing times must be finite and inside the preregistered window")
    duration = registration.window_end_s - registration.window_start_s
    if duration <= 0.0 or registration.effective_width_m <= 0.0:
        raise ValueError("saturated-flow window and width must be positive")
    total_bins = ceil(duration / registration.continuity_bin_s)
    active_bins = {
        min(
            total_bins - 1,
            int((value - registration.window_start_s) / registration.continuity_bin_s),
        )
        for value in times
    }
    active_fraction = len(active_bins) / total_bins
    specific_flow = len(times) / (registration.effective_width_m * duration)
    passed = (
        registration.minimum_specific_flow_p_m_s
        <= specific_flow
        <= registration.maximum_specific_flow_p_m_s
        and active_fraction >= registration.minimum_active_bin_fraction
    )
    return {
        "crossing_count": len(times),
        "window_duration_s": duration,
        "active_bin_count": len(active_bins),
        "total_bin_count": total_bins,
        "active_bin_fraction": active_fraction,
        "specific_flow_p_m_s": specific_flow,
        "gate_status": "pass" if passed else "fail",
        "release_eligible_for_step5": passed,
    }


def build_saturated_flow_artifact(
    *,
    scene_id: str,
    control_id: str,
    trajectory: pd.DataFrame,
    registration: SaturatedFlowRegistration,
    runtime_cohort: RuntimeCohort,
    source_movement_trace: ArtifactRecord,
) -> SaturatedFlowArtifact:
    registration_payload = {
        "registration_id": registration.registration_id,
        "coordinate_frame": registration.coordinate_frame,
        "line_start_m": list(registration.line_start_m),
        "line_end_m": list(registration.line_end_m),
        "crossing_direction": registration.crossing_direction,
        "effective_width_m": registration.effective_width_m,
        "window_start_s": registration.window_start_s,
        "window_end_s": registration.window_end_s,
        "continuity_bin_s": registration.continuity_bin_s,
        "minimum_active_bin_fraction": registration.minimum_active_bin_fraction,
        "minimum_specific_flow_p_m_s": registration.minimum_specific_flow_p_m_s,
        "maximum_specific_flow_p_m_s": registration.maximum_specific_flow_p_m_s,
        "physical_mapping": registration.physical_mapping,
    }
    measurements = evaluate_crossing_times(
        directed_crossing_times(trajectory, registration),
        registration,
    )
    return SaturatedFlowArtifact(
        schema_version=SATURATED_FLOW_SCHEMA_VERSION,
        scene_id=scene_id,
        control_id=control_id,
        registration=registration_payload,
        registration_sha256=canonical_sha256(registration_payload),
        runtime_cohort=runtime_cohort,
        source_movement_trace=source_movement_trace,
        **measurements,
    )
