from __future__ import annotations

from types import SimpleNamespace
import unittest

from sandbox.metro_station_sandbox.calibration.contracts import (
    VALIDATED,
    CalibrationProfile,
)
from sandbox.metro_station_sandbox.design import create_design
from metro_station_experiments.acceptance import (
    assess_experiment_results,
    assess_production_scenario,
    experiment_exit_code,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario


class ProductionAcceptanceTests(unittest.TestCase):
    def test_validated_physical_active_scenario_with_clearance_passes(self) -> None:
        decision = assess_production_scenario(_production_scenario())

        self.assertTrue(decision.passed, decision.as_dict())
        self.assertEqual("pass", decision.status)

    def test_default_compatibility_configuration_is_not_production_ready(self) -> None:
        scenario = _production_scenario(
            calibration_profile=CalibrationProfile(),
            simulation_clock_mode="legacy_scaled",
            goal_graph_mode="active",
            jupedsim_strict=False,
            station_design=None,
            demand_minutes=None,
            minutes=1,
        )

        decision = assess_production_scenario(scenario)
        codes = {issue.code for issue in decision.issues}

        self.assertFalse(decision.passed)
        self.assertEqual(
            {
                "calibration.not_validated",
                "clock.not_physical",
                "movement.not_strict",
                "design.missing",
                "horizon.no_clearance_window",
            },
            codes,
        )

    def test_experiment_failure_and_missing_diagnosis_block_release(self) -> None:
        results = [
            _result("trajectory", status="ok", verdict="fail"),
            _result("missing", status="ok", verdict=None),
            _result("error", status="error", verdict=None),
        ]

        decision = assess_experiment_results(results)

        self.assertFalse(decision.passed)
        self.assertEqual(1, experiment_exit_code(results))
        self.assertEqual(3, len(decision.issues))

    def test_warning_policy_is_explicit(self) -> None:
        results = [_result("warning", status="ok", verdict="warn")]

        self.assertEqual(0, experiment_exit_code(results))
        self.assertEqual(1, experiment_exit_code(results, fail_on_warning=True))

    def test_zero_demand_is_valid_but_negative_demand_is_rejected(self) -> None:
        zero = _production_scenario(
            entry_count_hour=0,
            exit_count_hour=0,
            transfer_count_hour=0,
        )

        self.assertEqual(0, zero.entry_groups + zero.exit_groups + zero.transfer_groups)
        for field_name in (
            "entry_count_hour",
            "exit_count_hour",
            "transfer_count_hour",
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, field_name):
                    _production_scenario(**{field_name: -1})

    def test_elevator_dispatch_threshold_cannot_exceed_capacity(self) -> None:
        equal_boundary = _production_scenario(
            elevator_cabin_capacity_persons=8,
            elevator_min_dispatch_persons=8,
        )
        over_capacity = _production_scenario(
            elevator_cabin_capacity_persons=8,
            elevator_min_dispatch_persons=9,
        )

        self.assertTrue(assess_production_scenario(equal_boundary).passed)
        decision = assess_production_scenario(over_capacity)
        self.assertFalse(decision.passed)
        self.assertIn(
            "facility.elevator_dispatch_exceeds_capacity",
            {issue.code for issue in decision.issues},
        )

    def test_disabled_facility_ids_reject_blank_and_duplicate_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "blank"):
            _production_scenario(disabled_facility_ids=("",))
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _production_scenario(disabled_facility_ids=("gate:1", "gate:1"))

    def test_train_time_boundaries_reject_negative_offset_and_invalid_production_ratio(self) -> None:
        with self.assertRaisesRegex(ValueError, "initial_train_offset_seconds"):
            _production_scenario(initial_train_offset_seconds=-1)

        equal_boundary = _production_scenario(
            train_dwell_seconds=60,
            train_headway_seconds=60,
        )
        invalid = _production_scenario(
            train_dwell_seconds=61,
            train_headway_seconds=60,
        )

        self.assertTrue(assess_production_scenario(equal_boundary).passed)
        self.assertIn(
            "train.dwell_exceeds_headway",
            {issue.code for issue in assess_production_scenario(invalid).issues},
        )


def _production_scenario(**overrides: object) -> StationSandboxScenario:
    values: dict[str, object] = {
        "station_name": "production_acceptance",
        "hour": 18,
        "minutes": 2,
        "tick_seconds": 1,
        "group_size": 1,
        "entry_count_hour": 60,
        "exit_count_hour": 60,
        "source_label": "unit",
        "sample_hours": 1,
        "demand_minutes": 1,
        "station_design": create_design("two_level_island_platform"),
        "movement_backend_name": "jupedsim",
        "jupedsim_strict": True,
        "simulation_clock_mode": "physical",
        "goal_graph_mode": "active",
        "calibration_profile": CalibrationProfile(
            profile_id="validated_unit",
            status=VALIDATED,
            calibration_dataset_id="calibration_day",
            validation_dataset_id="validation_day",
        ),
    }
    values.update(overrides)
    return StationSandboxScenario(**values)


def _result(case_id: str, *, status: str, verdict: str | None) -> SimpleNamespace:
    report = None
    if verdict is not None:
        report = SimpleNamespace(pass_fail=verdict, issues=[f"synthetic {verdict}"])
    return SimpleNamespace(
        case=SimpleNamespace(case_id=case_id),
        status=status,
        error="synthetic execution error" if status != "ok" else None,
        trajectory_report=report,
    )


if __name__ == "__main__":
    unittest.main()
