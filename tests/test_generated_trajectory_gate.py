from __future__ import annotations

from types import SimpleNamespace

import pytest

from metro_station_acceptance.generated_trajectory_gate import (
    _blind_config_from_evidence,
    _trajectory_authority_coverage,
    evaluate_generated_trajectory_gates,
)
from metro_station_acceptance import generated_simulation_run
from metro_station_acceptance import goal_journey_acceptance
from metro_station_acceptance import operational_acceptance_matrix
from metro_station_acceptance.generated_simulation_acceptance import (
    GeneratedSimulationAcceptanceReport,
)
from metro_station_acceptance.generated_simulation_run import GeneratedSimulationRecord
from metro_station_acceptance.generated_layout_evidence import (
    render_generated_simulation_markdown,
)
from metro_station_acceptance.generated_scale_acceptance import (
    merge_generated_simulation_shards,
)
from scripts import run_layout_acceptance
from metro_station_testkit.layout_recipe import LayoutRecipe


def _evidence() -> dict[str, object]:
    snapshots = []
    movement_points = []
    for sample_index in range(21):
        time_s = sample_index * 0.2
        x = sample_index * 0.2
        movement_points.append(
            {
                "passenger_id": 1,
                "time_seconds": time_s,
                "x": x,
                "y": 0.0,
                "level_id": "b1",
                "episode_id": "1:1",
                "sample_index": sample_index,
                "authority": "jupedsim",
                "phase": "walking",
            }
        )
        if sample_index % 5 == 0:
            snapshots.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": 1,
                            "x": x,
                            "y": 0.0,
                            "state": "walking_to_platform",
                        }
                    ],
                }
            )
    return {
        "simulation_trace": {
            "schema_version": "simulation_trace.v1",
            "metadata": {
                "scenario": {
                    "jupedsim_agent_radius_m": 0.18,
                }
            },
            "snapshots": snapshots,
            "movement_trace": {
                "schema_version": "movement_trace.v1",
                "metadata": {
                    "authority": "jupedsim",
                    "coverage": ["walking"],
                    "coordinates": "station_model_meters",
                    "sample_interval_seconds": 0.2,
                    "integration_dt_seconds": 0.01,
                    "visual_only": False,
                },
                "points": movement_points,
            },
        }
    }


@pytest.mark.parametrize("radius_m", (0.12, 0.18, 0.22))
def test_blind_colocation_threshold_is_derived_from_declared_agent_radius(
    radius_m: float,
) -> None:
    evidence = _evidence()
    evidence["simulation_trace"]["metadata"]["scenario"][
        "jupedsim_agent_radius_m"
    ] = radius_m

    config = _blind_config_from_evidence(evidence)

    assert config.maximum_near_colocation_distance_m == pytest.approx(radius_m * 2.0)


def test_scientific_gate_fails_closed_without_agent_radius_metadata() -> None:
    evidence = _evidence()
    del evidence["simulation_trace"]["metadata"]["scenario"][
        "jupedsim_agent_radius_m"
    ]

    report = evaluate_generated_trajectory_gates(
        seeds=(42,),
        normal_evidence={42: evidence},
        operational_evidence={},
        operational_scenario_id=None,
        applicable=True,
    )

    assert report["status"] == "fail"
    assert "jupedsim_agent_radius_m" in report["cases"][0]["error"]


def test_every_normal_and_operational_seed_runs_all_four_gates() -> None:
    evidence = _evidence()
    report = evaluate_generated_trajectory_gates(
        seeds=(41, 42, 43),
        normal_evidence={seed: evidence for seed in (41, 42, 43)},
        operational_evidence={
            ("congested", seed): evidence for seed in (41, 42, 43)
        },
        operational_scenario_id="congested",
        applicable=True,
    )

    assert report["status"] == "pass", report
    assert report["scientific_pass"] is True
    assert report["required_case_count"] == 6
    assert report["evaluated_case_count"] == 6
    assert {
        tuple(case["gates"])
        for case in report["cases"]
    } == {("truth", "kinematics", "composite", "blind")}
    assert all(
        case["authority_coverage"]["all_state_consumers_match"]
        and case["authority_coverage"]["unknown_authority_count"] == 0
        for case in report["cases"]
    )


def test_unregistered_process_trace_fails_closed() -> None:
    evidence = _evidence()
    evidence["simulation_trace"]["moving_walkway_trace"] = {
        "points": [{"passenger_id": 1, "time_seconds": 0.1, "x": 0.1, "y": 0.0}]
    }

    report = evaluate_generated_trajectory_gates(
        seeds=(42,),
        normal_evidence={42: evidence},
        operational_evidence={},
        operational_scenario_id=None,
        applicable=True,
    )

    assert report["status"] == "fail"
    assert "unregistered trajectory authority" in report["cases"][0]["error"]


def test_facility_episode_coverage_fails_when_one_declared_phase_is_deleted() -> None:
    evidence = _evidence_with_elevator_service()
    complete = _trajectory_authority_coverage(evidence)
    assert complete["all_state_consumers_match"] is True
    assert complete["facility_episode_coverage"]["obligation_count"] == 3

    points = evidence["simulation_trace"]["movement_trace"]["points"]
    evidence["simulation_trace"]["movement_trace"]["points"] = [
        point for point in points if point["phase"] != "elevator_unloading"
    ]
    incomplete = _trajectory_authority_coverage(evidence)

    assert incomplete["all_state_consumers_match"] is False
    assert incomplete["facility_episode_coverage"]["failed_obligation_count"] == 1
    assert incomplete["facility_episode_coverage"]["failed_obligations"][0][
        "phase"
    ] == "elevator_unloading"
    report = evaluate_generated_trajectory_gates(
        seeds=(42,),
        normal_evidence={42: evidence},
        operational_evidence={},
        operational_scenario_id=None,
        applicable=True,
    )
    assert report["status"] == "fail"
    assert report["cases"][0]["authority_coverage"][
        "all_state_consumers_match"
    ] is False


def test_train_door_service_requires_event_bound_process_truth() -> None:
    evidence = _evidence_with_train_door_service()
    complete = _trajectory_authority_coverage(evidence)

    assert complete["facility_episode_coverage"]["passed"] is True
    assert complete["facility_episode_coverage"]["obligation_count"] == 1
    evidence["simulation_trace"]["facility_motion_trace"]["points"].pop()
    incomplete = _trajectory_authority_coverage(evidence)
    assert incomplete["facility_episode_coverage"]["passed"] is False
    assert incomplete["facility_episode_coverage"]["failed_obligations"][0][
        "phase"
    ] == "train_door_boarding"


def test_missing_seed_evidence_fails_closed() -> None:
    report = evaluate_generated_trajectory_gates(
        seeds=(41, 42),
        normal_evidence={41: _evidence()},
        operational_evidence={},
        operational_scenario_id=None,
        applicable=True,
    )

    assert report["status"] == "fail"
    assert report["scientific_pass"] is False
    assert report["evaluated_case_count"] == 1
    assert report["cases"][1]["status"] == "missing"


def test_duplicate_seed_cannot_masquerade_as_complete_coverage() -> None:
    with pytest.raises(ValueError, match="unique"):
        evaluate_generated_trajectory_gates(
            seeds=(42, 42),
            normal_evidence={42: _evidence()},
            operational_evidence={},
            operational_scenario_id=None,
            applicable=True,
        )


def test_custom_backend_is_explicitly_not_applicable_without_evaluating_payload() -> None:
    report = evaluate_generated_trajectory_gates(
        seeds=(42,),
        normal_evidence={42: {"malformed": True}},
        operational_evidence={},
        operational_scenario_id="single_facility",
        applicable=False,
        not_applicable_reason="custom_movement_backend_factory",
    )

    assert report["status"] == "not_applicable"
    assert report["scientific_pass"] is None
    assert report["evaluated_case_count"] == 0
    assert report["reason"] == "custom_movement_backend_factory"


def test_not_applicable_record_never_becomes_scientific_pass() -> None:
    record = GeneratedSimulationRecord(
        "fake-backend-recipe",
        "normal",
        "single_facility",
        None,
        None,
        "deterministic",
        {
            "status": "not_applicable",
            "scientific_pass": None,
            "blind_observation_count": 0,
        },
        0,
        None,
        {"engineering_harness_pass": True},
    )
    report = GeneratedSimulationAcceptanceReport(
        tier="smoke",
        corpus_id="fake-backend",
        seeds=(42,),
        sampled_recipe_ids=(record.recipe_id,),
        global_sampled_recipe_ids=(record.recipe_id,),
        shard_index=0,
        shard_count=1,
        include_operations=False,
        records=(record,),
        checks={"engineering_harness_pass": True},
    )

    assert record.status == "ok"
    assert record.trajectory_scientific_status == "not_applicable"
    assert report.trajectory_scientific_status == "not_applicable"
    assert report.as_dict()["trajectory_scientific_status"] != "pass"
    assert "trajectory_science=not_applicable" in render_generated_simulation_markdown(
        report
    )

    merged = merge_generated_simulation_shards((report.as_dict(),))
    assert merged["status"] == "ok"
    assert merged["trajectory_scientific_status"] == "not_applicable"


def test_generated_run_collects_each_seed_for_normal_and_operation(monkeypatch) -> None:
    captured = {}
    run_configuration = {}
    evidence = _evidence()

    def fake_four_journeys(**kwargs):
        run_configuration["normal_tick_seconds"] = kwargs["normal_options"][
            "tick_seconds"
        ]
        for seed in kwargs["seeds"]:
            kwargs["trajectory_evidence_by_seed"][seed] = evidence
        return SimpleNamespace(status="ok", normal=(object(),))

    def fake_operations(**kwargs):
        run_configuration["operational_tick_seconds"] = kwargs["tick_seconds"]
        scenario_id = kwargs["scenario_ids"][0]
        for seed in kwargs["seeds"]:
            kwargs["trajectory_evidence_by_case"][(scenario_id, seed)] = evidence
        return SimpleNamespace(status="ok")

    def fake_goal_graph(**kwargs):
        run_configuration["replay_tick_seconds"] = kwargs["tick_seconds"]
        return SimpleNamespace(
            walking_cost_source_counts={"physical_waypoint_geodesic": 1},
            walking_cost_evaluation_count=1,
        )

    def fake_gate(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "scientific_pass": True,
            "required_case_count": 6,
            "evaluated_case_count": 6,
            "blind_observation_count": 120,
        }

    monkeypatch.setattr(generated_simulation_run, "generate_layout", lambda _recipe: object())
    monkeypatch.setattr(
        generated_simulation_run,
        "run_four_journey_acceptance",
        fake_four_journeys,
    )
    monkeypatch.setattr(
        generated_simulation_run,
        "run_operational_acceptance_matrix",
        fake_operations,
    )
    monkeypatch.setattr(
        generated_simulation_run,
        "run_goal_graph_acceptance",
        fake_goal_graph,
    )
    monkeypatch.setattr(generated_simulation_run, "_fingerprint", lambda _report: "same")
    monkeypatch.setattr(
        generated_simulation_run,
        "evaluate_generated_trajectory_gates",
        fake_gate,
    )

    record = generated_simulation_run.run_generated_recipe_simulation(
        _recipe(),
        (41, 42, 43),
        {
            "entry_count_hour": 1,
            "exit_count_hour": 1,
            "transfer_count_hour": 1,
            "demand_minutes": 1,
            "clearance_minutes": 1,
        },
        1,
        1,
        True,
        None,
    )

    assert record.status == "ok", record
    assert set(captured["normal_evidence"]) == {41, 42, 43}
    assert set(captured["operational_evidence"]) == {
        ("single_facility", 41),
        ("single_facility", 42),
        ("single_facility", 43),
    }
    assert run_configuration == {
        "normal_tick_seconds": 1,
        "operational_tick_seconds": 1,
        "replay_tick_seconds": 1,
    }


def test_normal_and_operational_harnesses_export_each_case(monkeypatch) -> None:
    normal_evidence = {}
    operational_evidence = {}

    def fake_normal(**kwargs):
        kwargs["trajectory_evidence"].update({"seed": kwargs["seed"]})
        return SimpleNamespace(status="ok")

    def fake_evacuation(**_kwargs):
        return SimpleNamespace(status="ok")

    def fake_operational(scenario_id, **kwargs):
        kwargs["trajectory_evidence"].update(
            {"scenario_id": scenario_id, "seed": kwargs["seed"]}
        )
        return SimpleNamespace(status="ok")

    monkeypatch.setattr(
        goal_journey_acceptance,
        "run_goal_graph_acceptance",
        fake_normal,
    )
    monkeypatch.setattr(
        goal_journey_acceptance,
        "run_evacuation_acceptance",
        fake_evacuation,
    )
    monkeypatch.setattr(
        operational_acceptance_matrix,
        "run_operational_acceptance",
        fake_operational,
    )

    goal_journey_acceptance.run_four_journey_acceptance(
        seeds=(41, 42, 43),
        trajectory_evidence_by_seed=normal_evidence,
    )
    operational_acceptance_matrix.run_operational_acceptance_matrix(
        seeds=(41, 42, 43),
        scenario_ids=("congested",),
        trajectory_evidence_by_case=operational_evidence,
    )

    assert normal_evidence == {
        41: {"seed": 41},
        42: {"seed": 42},
        43: {"seed": 43},
    }
    assert operational_evidence == {
        ("congested", 41): {"scenario_id": "congested", "seed": 41},
        ("congested", 42): {"scenario_id": "congested", "seed": 42},
        ("congested", 43): {"scenario_id": "congested", "seed": 43},
    }


def test_trajectory_cli_dispatches_dedicated_profile(monkeypatch) -> None:
    captured = {}

    def fake_run(args):
        captured["tier"] = args.tier
        return 17

    monkeypatch.setattr(run_layout_acceptance, "_run_trajectory_tier", fake_run)

    assert run_layout_acceptance.main(["--tier", "trajectory"]) == 17
    assert captured == {"tier": "trajectory"}


def test_trajectory_cli_rejects_overrides_that_weaken_sixteen_by_three_profile() -> None:
    with pytest.raises(SystemExit):
        run_layout_acceptance.main(
            ["--tier", "trajectory", "--seeds", "42"]
        )


def _evidence_with_elevator_service() -> dict[str, object]:
    evidence = _evidence()
    trace = evidence["simulation_trace"]
    trace["facility_events"] = [
        {
            "event_id": 1,
            "facility_id": "elevator:a",
            "facility_kind": "elevator",
            "passenger_ids": [1],
            "start_time": 0.0,
            "board_end_time": 0.2,
            "arrive_time": 0.4,
            "end_time": 0.6,
        }
    ]
    trace["facility_motion_trace"] = {
        "schema_version": "facility_motion_trace.v1",
        "metadata": {
            "authority": "facility_process_model",
            "coverage": ["elevator_travel"],
            "sample_interval_seconds": 0.2,
            "visual_only": False,
        },
        "points": [
            {
                "passenger_id": 1,
                "time_seconds": start,
                "x": start,
                "y": 0.0,
                "level_id": "connector:elevator:a",
                "phase": phase,
                "episode_id": f"elevator:a:1:{phase.removeprefix('elevator_')}",
                "sample_index": index,
                "authority": "facility_process_model",
                "visual_only": False,
            }
            for index, (phase, start) in enumerate(
                (("elevator_travel", 0.2), ("elevator_travel", 0.4))
            )
        ],
    }
    movement = trace["movement_trace"]
    movement["points"] = [
        *movement["points"],
        *[
            {
                "passenger_id": 1,
                "time_seconds": time_s,
                "x": time_s,
                "y": 0.0,
                "level_id": level_id,
                "phase": phase,
                "episode_id": f"elevator:a:1:{phase}:native",
                "sample_index": index,
                "authority": "jupedsim_committed_walk",
                "visual_only": False,
            }
            for phase, level_id, samples in (
                ("elevator_boarding", "b1", (0.0, 0.2)),
                ("elevator_unloading", "b2", (0.4, 0.6)),
            )
            for index, time_s in enumerate(samples)
        ],
    ]
    return evidence


def _evidence_with_train_door_service() -> dict[str, object]:
    evidence = _evidence()
    trace = evidence["simulation_trace"]
    trace["facility_events"] = [
        {
            "event_id": 7,
            "facility_id": "train_door:a",
            "facility_kind": "train_door",
            "passenger_ids": [1],
            "start_time": 1.0,
            "end_time": 1.4,
        }
    ]
    trace["facility_motion_trace"] = {
        "schema_version": "facility_motion_trace.v1",
        "metadata": {
            "authority": "facility_process_model",
            "coverage": ["train_door_boarding"],
            "sample_interval_seconds": 0.2,
            "visual_only": False,
        },
        "points": [
            {
                "passenger_id": 1,
                "time_seconds": time_s,
                "x": time_s,
                "y": 0.0,
                "level_id": "train_door:a",
                "phase": "train_door_boarding",
                "episode_id": "train_door:train_door:a:7:boarding",
                "sample_index": index,
                "authority": "facility_process_model",
                "visual_only": False,
            }
            for index, time_s in enumerate((1.0, 1.2, 1.4))
        ],
    }
    return evidence


def _recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="trajectory-profile-test",
        seed=7,
        archetype="single_terminal",
        entrance_count=1,
        gate_count=1,
        elevator_count=0,
        stairs_count=0,
        escalator_pair_count=0,
        mirror=False,
        asset_density="sparse",
        geometry_variant=0,
    )
