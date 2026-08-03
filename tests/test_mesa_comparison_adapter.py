from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.comparison import MesaComparisonExecutor
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.application.analysis_cases import clone_analysis_case, create_analysis_case
from metro_station.application.comparisons import ComparisonRunSpec
from metro_station.application.control_plans import (
    DEPLOY,
    REMOVE,
    WATER_BARRIER,
    ControlEvent,
    ControlMeasure,
    ControlPlan,
)


def test_mesa_comparison_executes_frozen_case_with_clearance_window() -> None:
    baseline = create_analysis_case(
        name="Baseline",
        design=create_design("single_level_terminal").as_dict(),
        operations={"entry_count_hour": 0, "exit_count_hour": 0},
        simulation={
            "demand_minutes": 1,
            "horizon_minutes": 2,
            "tick_seconds": 30,
            "movement_backend": "batched_jupedsim",
        },
        seeds=(7,),
    )
    candidate = clone_analysis_case(baseline, name="Candidate")
    active_spec = ComparisonRunSpec.create(baseline, candidate)

    result = MesaComparisonExecutor().execute(
        baseline,
        seed=7,
        role="baseline",
        spec=active_spec,
    )

    assert result.status == "ok"
    assert result.case_id == baseline.case_id
    assert result.seed == 7
    assert result.cleared is True
    assert result.right_censored is False
    assert result.total_agents == 0


def test_comparison_spec_keeps_frozen_simulation_controls() -> None:
    baseline = create_analysis_case(
        name="Baseline",
        design=create_design("single_level_terminal").as_dict(),
        operations={},
        simulation={"demand_minutes": 1, "horizon_minutes": 2, "tick_seconds": 30},
    )
    candidate = clone_analysis_case(baseline, name="Candidate")
    candidate = replace(
        candidate,
        simulation={**candidate.simulation, "movement_backend": "jupedsim"},
    )

    try:
        ComparisonRunSpec.create(baseline, candidate)
    except ValueError as exc:
        assert "simulation controls" in str(exc)
    else:
        raise AssertionError("mismatched simulation controls must be rejected")


def test_analysis_case_control_plan_runs_and_enters_summary_evidence() -> None:
    plan = ControlPlan(
        plan_id="comparison_timeline",
        name="Timed water barrier",
        measures=(
            ControlMeasure(
                "water_a",
                WATER_BARRIER,
                "Water barrier A",
                level_id="l1_terminal",
                parameters={
                    "geometry": {
                        "shape": "rect",
                        "x_m": 50.0,
                        "y_m": 28.0,
                        "width_m": 2.0,
                        "height_m": 1.5,
                    }
                },
            ),
        ),
        events=(
            ControlEvent("deploy_water", "water_a", 0, DEPLOY),
            ControlEvent("remove_water", "water_a", 30, REMOVE),
        ),
    )
    baseline = create_analysis_case(
        name="Timed baseline",
        design=create_design("single_level_terminal").as_dict(),
        operations={"entry_count_hour": 0, "exit_count_hour": 0},
        simulation={
            "demand_minutes": 1,
            "horizon_minutes": 2,
            "tick_seconds": 30,
            "movement_backend": "batched_jupedsim",
            "control_plan": plan.as_dict(),
        },
        seeds=(7,),
    )
    candidate = clone_analysis_case(baseline, name="Timed candidate")
    active_spec = ComparisonRunSpec.create(baseline, candidate)

    result = MesaComparisonExecutor().execute(
        baseline,
        seed=7,
        role="baseline",
        spec=active_spec,
    )

    assert result.status == "ok"
    assert [event["event_id"] for event in result.control_events] == [
        "deploy_water",
        "remove_water",
    ]
    assert {event["status"] for event in result.control_events} == {"applied"}
