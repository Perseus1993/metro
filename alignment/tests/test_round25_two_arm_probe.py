from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from metro_station_testkit.two_arm_probe import build_two_arm_report


def _load_probe_script():
    path = Path(__file__).parents[1] / "scripts" / "run_round25_two_arm_probe.py"
    spec = importlib.util.spec_from_file_location("round25_probe_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arm() -> dict:
    return {
        "seed": 42,
        "design_sha256": "d" * 64,
        "entry_count_hour": 2500,
        "exit_count_hour": 2200,
        "horizon_steps": 120,
        "demand_steps": 120,
        "movement_model": {"backend": "jupedsim"},
        "scene_config": {
            "seed": 42,
            "gate_service_persons_per_min": 55,
            "entry_admission_token_capacity": 26,
        },
    }


def test_two_arm_probe_freezes_every_non_target_input() -> None:
    report = build_two_arm_report(
        finite=_arm(),
        enlarged=_arm(),
        controlled_fields=("entry_admission_token_capacity",),
    )

    assert report["status"] == "pass"
    assert report["controlled_difference"]["name"] == "admission_capacity_mode"


def test_two_arm_probe_rejects_seed_drift() -> None:
    enlarged = _arm()
    enlarged["seed"] = 43

    with pytest.raises(RuntimeError, match="seed"):
        build_two_arm_report(
            finite=_arm(),
            enlarged=enlarged,
            controlled_fields=("entry_admission_token_capacity",),
        )


def test_two_arm_probe_rejects_non_target_scene_config_drift() -> None:
    enlarged = _arm()
    enlarged["scene_config"]["gate_service_persons_per_min"] = 56

    with pytest.raises(RuntimeError, match="scene_config_without_controlled_fields"):
        build_two_arm_report(
            finite=_arm(),
            enlarged=enlarged,
            controlled_fields=("entry_admission_token_capacity",),
        )


def test_two_arm_probe_rejects_runtime_cohort_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _load_probe_script()
    expected = {
        "metro_runtime_fingerprint": {"content_sha256": "a" * 64},
        "analysis_runtime_fingerprint": {"content_sha256": "b" * 64},
    }
    monkeypatch.setattr(
        probe,
        "_runtime_cohort",
        lambda: {
            **expected,
            "analysis_runtime_fingerprint": {"content_sha256": "c" * 64},
        },
    )

    with pytest.raises(RuntimeError, match="mixed-cohort evidence"):
        probe._require_runtime_cohort(expected, phase="test")


def test_round24_baseline_is_anchored_to_committed_handoff() -> None:
    baseline = _load_probe_script()._round24_historical_baseline()

    assert baseline["source"]["commit"] == "0b938dcdea9a117d7d3fe96cbb30c8f9520d811f"
    assert baseline["arms"]["finite_admission"]["pending_entry"] == 8
    assert baseline["arms"]["finite_admission"]["admission_exhausted"] == 90
    assert baseline["arms"]["finite_admission"]["deferred_downstream"] == 89


def test_terminal_diagnostics_retain_lifecycle_closed_owners() -> None:
    probe = _load_probe_script()
    runtime = SimpleNamespace(
        passengers=[],
        alignment_admission_resources={
            "exit": SimpleNamespace(
                owners=(),
                completed_residences=(
                    SimpleNamespace(owner_id=145, right_censored=True),
                    SimpleNamespace(owner_id=131, right_censored=False),
                ),
            )
        },
    )

    diagnostics = probe._terminal_admission_owner_diagnostics(runtime)

    assert diagnostics == {
        "exit": [{"owner_id": 145, "passenger_present": False}],
    }
