from __future__ import annotations

import pytest

from metro_alignment.round27_acceptance import (
    ClearanceBottleneckInput,
    ThroughputFloor,
    evaluate_clearance_gate,
    evaluate_dynamic_gate,
    evaluate_stress_gate,
    preregister_clearance_prediction,
)


def _floor() -> ThroughputFloor:
    return ThroughputFloor(
        "entry",
        783,
        300,
        240,
        "qualification.json#runs",
        "empirical_qualification",
        "a" * 64,
        "b" * 40,
    )


def _boundary(**updates: int) -> dict[str, int]:
    values = {
        "scheduled_persons": 783,
        "admitted_persons": 310,
        "source_waiting_persons": 473,
        "active_inside_persons": 60,
        "completed_persons": 250,
        "not_alighted_persons": 0,
        "dropped_persons": 0,
    }
    values.update(updates)
    return values


def test_dynamic_gate_allows_visible_source_backlog_but_requires_service_floor() -> None:
    report = evaluate_dynamic_gate(
        {"entry": _boundary()},
        [_floor()],
        run_outcome_code=None,
        liveness_violations=0,
        round26_replan_ratio=0.006,
        round26_placement_retry_ratio=0.0,
    )

    assert report["status"] == "pass"


def test_dynamic_gate_rejects_conserved_zero_service() -> None:
    boundary = _boundary(
        admitted_persons=0,
        source_waiting_persons=783,
        active_inside_persons=0,
        completed_persons=0,
    )

    report = evaluate_dynamic_gate(
        {"entry": boundary},
        [_floor()],
        run_outcome_code=None,
        liveness_violations=0,
        round26_replan_ratio=0.0,
        round26_placement_retry_ratio=0.0,
    )

    assert report["status"] == "fail"
    assert {item["id"] for item in report["checks"] if item["status"] == "fail"} == {
        "entry.admission_floor",
        "entry.completion_floor",
    }


def test_dynamic_gate_rejects_structured_run_failure_even_when_floors_pass() -> None:
    report = evaluate_dynamic_gate(
        {"entry": _boundary()},
        [_floor()],
        run_outcome_code="train_alighting_capacity_insufficient",
        liveness_violations=0,
        round26_replan_ratio=0.0,
        round26_placement_retry_ratio=0.0,
    )

    assert report["status"] == "fail"
    assert [item["id"] for item in report["checks"] if item["status"] == "fail"] == [
        "run_outcome_success"
    ]


def test_throughput_floor_must_be_positive_andinternally_ordered() -> None:
    with pytest.raises(ValueError, match="minimum_completed"):
        ThroughputFloor(
            "entry",
            10,
            5,
            6,
            "evidence",
            "empirical_qualification",
            "a" * 64,
            "b" * 40,
        )


def test_clearance_prediction_is_derived_not_trial_selected() -> None:
    prediction = preregister_clearance_prediction(
        [
            ClearanceBottleneckInput(
                "gate", 101, 10.0, 3, "proved:gate", "analytic_proof", "a" * 64
            ),
            ClearanceBottleneckInput(
                "walk-tail", 5, 2.0, 4, "proved:walk", "analytic_proof", "b" * 64
            ),
        ],
        pipeline_proved=True,
        pipeline_evidence_ref="proved:pipeline",
        pipeline_evidence_sha256="c" * 64,
    )

    assert prediction["predicted_clearance_upper_steps"] == 14
    assert prediction["composition"] == "maximum"


def test_clearance_prediction_without_proved_rate_is_unavailable() -> None:
    prediction = preregister_clearance_prediction([], pipeline_proved=False)

    report = evaluate_clearance_gate(
        prediction=prediction,
        observed_clearance_steps=1,
        source_waiting_persons=0,
        active_inside_persons=0,
        queue_persons=0,
        owner_persons=0,
        dropped_persons=0,
        flow_conserved=True,
        liveness_violations=0,
        run_outcome_code=None,
        scheduled_alighting_persons=0,
        expected_train_runs=0,
        train_manifests=[],
    )

    assert prediction["status"] == "prediction_unavailable"
    assert report["status"] == "fail"


def test_clearance_gate_requires_alighting_before_successful_departure() -> None:
    prediction = preregister_clearance_prediction(
        [
            ClearanceBottleneckInput(
                "exit", 20, 4.0, 2, "proved:exit", "analytic_proof", "a" * 64
            )
        ],
        pipeline_proved=True,
        pipeline_evidence_ref="proved:pipeline",
        pipeline_evidence_sha256="b" * 64,
    )
    manifest = {
        "departure_status": "departed",
        "planned_alight_persons": 20,
        "released_alight_persons": 20,
        "not_alighted_persons": 0,
        "alighting_release_complete_step": 8,
        "actual_departure_step": 9,
    }

    assert (
        evaluate_clearance_gate(
            prediction=prediction,
            observed_clearance_steps=7,
            source_waiting_persons=0,
            active_inside_persons=0,
            queue_persons=0,
            owner_persons=0,
            dropped_persons=0,
            flow_conserved=True,
            liveness_violations=0,
            run_outcome_code=None,
            scheduled_alighting_persons=20,
            expected_train_runs=1,
            train_manifests=[manifest],
        )["status"]
        == "pass"
    )

    manifest["alighting_release_complete_step"] = 10
    assert (
        evaluate_clearance_gate(
            prediction=prediction,
            observed_clearance_steps=7,
            source_waiting_persons=0,
            active_inside_persons=0,
            queue_persons=0,
            owner_persons=0,
            dropped_persons=0,
            flow_conserved=True,
            liveness_violations=0,
            run_outcome_code=None,
            scheduled_alighting_persons=20,
            expected_train_runs=1,
            train_manifests=[manifest],
        )["status"]
        == "fail"
    )


def test_stress_gate_rejects_vacuous_and_accepts_exercised_capacity() -> None:
    empty = {
        "scheduled_demand_persons": 0,
        "eligible_service_opportunities": 0,
        "completed_persons": 0,
        "admission_exhausted_attempts": 0,
        "source_waiting_persons": 0,
        "active_inside_persons": 0,
        "not_alighted_persons": 0,
        "dropped_persons": 0,
        "run_outcome_code": None,
        "unhandled_expected_capacity_exceptions": 0,
    }
    assert evaluate_stress_gate(empty)["status"] == "fail"

    exercised = dict(empty)
    exercised.update(
        scheduled_demand_persons=10,
        eligible_service_opportunities=3,
        completed_persons=4,
        source_waiting_persons=4,
        admission_exhausted_attempts=2,
        active_inside_persons=2,
    )
    assert evaluate_stress_gate(exercised)["status"] == "pass"
