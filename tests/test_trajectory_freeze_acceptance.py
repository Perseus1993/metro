from __future__ import annotations

import json

import pytest

from metro_station_acceptance import trajectory_freeze_acceptance as subject


def test_freeze_requires_unique_case_ids(tmp_path) -> None:
    duplicate = subject.TrajectoryFreezeSpec(
        case_id="same",
        run_kind="evacuation",
        layout_id="three_level_transfer",
        seed=7,
        initial_persons=10,
        minutes=1,
    )
    with pytest.raises(ValueError, match="case_id values must be unique"):
        subject.run_trajectory_freeze_acceptance(
            tmp_path,
            specs=(duplicate, duplicate),
        )


def test_freeze_writes_replay_blind_and_all_gate_results(monkeypatch, tmp_path) -> None:
    evidence = {
        "agents": [],
        "simulation_trace": {
            "metadata": {"scenario": {"jupedsim_agent_radius_m": 0.18}},
            "snapshots": [],
            "movement_trace": {"points": []},
            "facility_motion_trace": {"points": []},
        },
    }

    class DomainReport:
        def as_dict(self):
            return {"status": "ok"}

    monkeypatch.setattr(
        subject,
        "run_evacuation_acceptance",
        lambda **kwargs: (kwargs["trajectory_evidence"].update(evidence) or DomainReport()),
    )
    monkeypatch.setattr(
        subject,
        "evaluate_generated_trajectory_gates",
        lambda **kwargs: {
            "cases": [
                {
                    "status": "pass",
                    "gates": {
                        name: {"passed": True}
                        for name in ("truth", "kinematics", "composite", "blind")
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        subject,
        "analyze_presentation_fidelity",
        lambda payload: {"passed": True},
    )
    monkeypatch.setattr(
        subject,
        "anonymized_xy_observations",
        lambda payload: [{"track_id": 0, "t": 0.0, "x": 1.0, "y": 2.0}],
    )
    spec = subject.TrajectoryFreezeSpec(
        case_id="evacuation_10",
        run_kind="evacuation",
        layout_id="three_level_transfer",
        seed=7,
        initial_persons=10,
        minutes=1,
    )

    report = subject.run_trajectory_freeze_acceptance(tmp_path, specs=(spec,))

    assert report["status"] == "pass"
    assert json.loads((tmp_path / "evacuation_10.replay.json").read_text("utf-8")) == evidence
    assert json.loads((tmp_path / "evacuation_10.blind_xy.json").read_text("utf-8"))[0]["x"] == 1.0
    assert "PASS" in (tmp_path / "trajectory_freeze_report.md").read_text("utf-8")
