from __future__ import annotations

import pytest

from metro_alignment.source_integrity_gate import (
    evaluate_source_integrity_gate,
    require_source_integrity_gate,
)


def _passing_metrics() -> dict:
    return {
        "spawned_entry_persons": 83,
        "spawned_exit_persons": 73,
        "alignment_scheduled_entry_persons": 83,
        "alignment_scheduled_exit_persons": 73,
        "alignment_pending_entry_persons": 0,
        "alignment_pending_exit_persons": 0,
        "alignment_pending_entry_groups": 0,
        "alignment_pending_exit_groups": 0,
        "alignment_pending_source_persons": 0,
        "alignment_pending_source_groups": 0,
        "alignment_entry_max_pending_residence_steps": 9,
        "alignment_exit_max_pending_residence_steps": 9,
        "alignment_entry_admission_exhausted_ratio": 0.05,
        "alignment_exit_admission_exhausted_ratio": 0.05,
        "alignment_entry_dropped_persons": 0,
        "alignment_exit_dropped_persons": 0,
        "alignment_source_dropped_persons": 0,
        "alignment_entry_demand_conserved": True,
        "alignment_exit_demand_conserved": True,
        "alignment_source_demand_conserved": True,
        "audit_counts": {"passenger_liveness_violation": 0},
    }


def test_round25_source_integrity_thresholds_are_exact() -> None:
    report = evaluate_source_integrity_gate(_passing_metrics())

    assert report["status"] == "pass"
    assert report["thresholds"] == {
        "max_pending_residence_steps_exclusive": 10,
        "max_admission_exhausted_ratio": 0.05,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alignment_entry_max_pending_residence_steps", 10),
        ("alignment_exit_max_pending_residence_steps", 10),
        ("alignment_entry_admission_exhausted_ratio", 0.050001),
        ("alignment_exit_admission_exhausted_ratio", 0.050001),
        ("alignment_entry_dropped_persons", 1),
        ("alignment_exit_demand_conserved", False),
    ],
)
def test_round25_source_integrity_rejects_each_boundary_breach(
    field: str,
    value,
) -> None:
    metrics = _passing_metrics()
    metrics[field] = value

    with pytest.raises(RuntimeError, match=field):
        require_source_integrity_gate(metrics)
