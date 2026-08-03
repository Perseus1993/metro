from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .composite_trajectory_gate import analyze_composite_trajectory
from .presentation_fidelity_gate import analyze_presentation_fidelity
from .trajectory_kinematics_gate import analyze_trajectory_kinematics
from .trajectory_truth_gate import analyze_trajectory_truth


TRAJECTORY_ACCEPTANCE_SCHEMA_VERSION = "trajectory_acceptance.v1"


def run_trajectory_acceptance(
    *,
    scientific_payload: object,
    presentation_payload: object,
) -> dict[str, Any]:
    """Compose scientific and presentation gates without mixing their evidence."""

    truth = analyze_trajectory_truth(scientific_payload)
    kinematics = analyze_trajectory_kinematics(scientific_payload)
    composite = analyze_composite_trajectory(scientific_payload)
    presentation = analyze_presentation_fidelity(presentation_payload)
    reports: dict[str, Mapping[str, Any]] = {
        "simulation_truth": truth,
        "walking_kinematics": kinematics,
        "all_state_composite_trajectory": composite,
        "presentation_fidelity": presentation,
    }
    failed = [name for name, report in reports.items() if not bool(report.get("passed"))]
    return {
        "schema_version": TRAJECTORY_ACCEPTANCE_SCHEMA_VERSION,
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "evidence_boundaries": {
            "simulation_truth": "simulation_trace.snapshots",
            "walking_kinematics": "simulation_trace.movement_trace",
            "all_state_composite_trajectory": (
                "simulation_trace.snapshots + simulation_trace.movement_trace"
            ),
            "presentation_fidelity": "full_bundle.agents",
            "presentation_data_used_for_scientific_checks": False,
        },
        "reports": reports,
        "summary": {"failed_gates": failed, "failed_gate_count": len(failed)},
    }
