from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest
from pydantic import ValidationError

from metro_alignment.formal_contract import ArtifactRecord, RuntimeCohort
from metro_alignment.formal_profiles import ENTRY_TAIL_SATURATED_FLOW
from metro_alignment.saturated_flow import (
    SaturatedFlowArtifact,
    build_saturated_flow_artifact,
    directed_crossing_times,
    evaluate_crossing_times,
)


def _threshold_registration():
    return replace(
        ENTRY_TAIL_SATURATED_FLOW,
        effective_width_m=1.0,
        window_start_s=0.0,
        window_end_s=10.0,
        continuity_bin_s=1.0,
        minimum_active_bin_fraction=0.0,
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    [(11, "fail"), (12, "pass"), (15, "pass"), (16, "fail")],
)
def test_specific_flow_has_bilateral_1_2_to_1_5_gate(count: int, expected: str) -> None:
    result = evaluate_crossing_times(
        tuple((index + 0.5) * 10.0 / count for index in range(count)),
        _threshold_registration(),
    )
    assert result["gate_status"] == expected


def test_directed_measurement_line_counts_only_registered_direction_and_segment() -> None:
    frame = pd.DataFrame(
        [
            (1, 120.0, 7.0, 18.0),
            (1, 121.0, 9.0, 18.0),
            (2, 122.0, 9.0, 18.2),
            (2, 123.0, 7.0, 18.2),
            (3, 124.0, 7.0, 20.5),
            (3, 125.0, 9.0, 20.5),
        ],
        columns=("agent_id", "t_s", "x_m", "y_m"),
    )
    assert directed_crossing_times(frame, ENTRY_TAIL_SATURATED_FLOW) == (120.5,)


def test_saturated_artifact_rejects_a_forged_pass() -> None:
    registration = _threshold_registration()
    rows = []
    for agent_id in range(12):
        crossing = (agent_id + 0.5) * 10.0 / 12
        rows.extend(
            ((agent_id, crossing - 0.1, 7.0, 18.0), (agent_id, crossing + 0.1, 9.0, 18.0))
        )
    cohort = RuntimeCohort.create(
        scene_id="platform_boarding",
        base_scene_config_sha256="a" * 64,
        design_sha256="b" * 64,
        metro_runtime_fingerprint={"metro": "stable"},
        analysis_runtime_fingerprint={"analysis": "stable"},
    )
    artifact = build_saturated_flow_artifact(
        scene_id="platform_boarding",
        control_id="entry-tail-saturated-flow",
        trajectory=pd.DataFrame(rows, columns=("agent_id", "t_s", "x_m", "y_m")),
        registration=registration,
        runtime_cohort=cohort,
        source_movement_trace=ArtifactRecord(
            path="trace.json", sha256="c" * 64, size_bytes=1
        ),
    )
    assert artifact.gate_status == "pass"
    forged = artifact.model_dump()
    forged["specific_flow_p_m_s"] = 1.6
    with pytest.raises(ValidationError, match="verdict contradicts"):
        SaturatedFlowArtifact.model_validate(forged)
