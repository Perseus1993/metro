from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import run_metro_emergency_matrix as emergency


EXIT_GATES = tuple(
    f"exit_gate:exit_gate_bank_a:lane_{lane}" for lane in range(1, 5)
)


class MetroEmergencyMatrixTests(unittest.TestCase):
    def _args(self, *extra: str):
        return emergency.build_parser().parse_args(
            [
                "--populations",
                "10",
                "--seeds",
                "42",
                "--minutes",
                "6",
                "--tick-seconds",
                "1",
                "--min-completion-rate",
                "1",
                "--max-clearance-seconds",
                "360",
                "--max-final-station-persons",
                "0",
                *extra,
            ]
        )

    def test_zero_population_is_exact_success_boundary(self) -> None:
        args = self._args("--populations", "0")
        row = emergency.run_case(args, emergency.EmergencyCase(0, 42))

        self.assertEqual(0, row["spawned_persons"])
        self.assertEqual(0, row["remaining_persons"])
        self.assertEqual(1.0, row["completion_rate"])
        self.assertEqual(0.0, row["clearance_time_seconds"])
        self.assertEqual(0, row["population_accounting_error_persons"])
        self.assertEqual("pass", row["acceptance_status"])

    def test_small_active_goal_evacuation_clears_and_reports_density(self) -> None:
        args = self._args("--max-local-density-persons-m2", "10")
        row = emergency.run_case(args, emergency.EmergencyCase(10, 42))

        self.assertEqual(10, row["evacuated_persons"])
        self.assertEqual(0, row["remaining_persons"])
        self.assertGreater(row["clearance_time_seconds"], 0.0)
        self.assertLessEqual(row["clearance_time_seconds"], 360.0)
        self.assertGreater(row["peak_local_density_persons_m2"], 0.0)
        self.assertEqual("pass", row["acceptance_status"])

    def test_all_exit_gates_closed_fails_without_false_evacuation(self) -> None:
        disabled = [
            value
            for facility_id in EXIT_GATES
            for value in ("--disable-facility", facility_id)
        ]
        args = self._args("--minutes", "4", *disabled)
        row = emergency.run_case(args, emergency.EmergencyCase(10, 42))

        self.assertEqual(0, row["evacuated_persons"])
        self.assertEqual(10, row["remaining_persons"])
        self.assertEqual(0, row["population_accounting_error_persons"])
        self.assertIsNone(row["clearance_time_seconds"])
        self.assertEqual("fail", row["acceptance_status"])

    def test_all_exit_gates_closed_waits_without_jupedsim_busy_loop(self) -> None:
        disabled = [
            value
            for facility_id in EXIT_GATES
            for value in ("--disable-facility", facility_id)
        ]
        args = self._args("--minutes", "4", *disabled)
        model = emergency.MetroStationModel(
            emergency.make_scenario(args, emergency.EmergencyCase(10, 42)),
            seed=42,
        )

        model.run()

        self.assertTrue(
            all(
                passenger.goal_runtime.state.current_stage == "exit_gate"
                and passenger.goal_runtime.state.commitment is None
                for passenger in model.passengers
            )
        )

    def test_waiting_exit_choice_wakes_when_a_gate_recovers(self) -> None:
        disabled = [
            value
            for facility_id in EXIT_GATES[1:]
            for value in ("--disable-facility", facility_id)
        ]
        args = self._args(
            "--minutes",
            "8",
            "--facility-event",
            f"0:disable:{EXIT_GATES[0]}",
            "--facility-event",
            f"60:enable:{EXIT_GATES[0]}",
            *disabled,
        )

        row = emergency.run_case(args, emergency.EmergencyCase(10, 42))

        self.assertEqual(1.0, row["completion_rate"])
        self.assertEqual(0, row["remaining_persons"])

    def test_population_must_be_divisible_by_group_size(self) -> None:
        args = self._args("--populations", "1", "--group-size", "2")

        with self.assertRaisesRegex(ValueError, "divisible"):
            emergency.make_scenario(args, emergency.EmergencyCase(1, 42))

    def test_production_preflight_accepts_ready_emergency_configuration(self) -> None:
        args = self._args(
            "--production-acceptance",
            "--calibration-status",
            "validated",
            "--calibration-dataset-id",
            "calibration_day",
            "--validation-dataset-id",
            "validation_day",
        )

        self.assertEqual(
            [],
            emergency.production_preflight_issues(
                args,
                emergency.EmergencyCase(10, 42),
            ),
        )

    def test_nonfinite_density_limit_is_rejected_by_cli(self) -> None:
        for value in ("nan", "inf", "-inf", "0"):
            with self.subTest(value=value):
                with self.assertRaises(emergency.argparse.ArgumentTypeError):
                    emergency.positive_float(value)

    def test_fault_event_at_horizon_is_rejected(self) -> None:
        invalid_events = ("360:disable:exit_gate:exit_gate_bank_a:lane_1",)
        for event in invalid_events:
            with self.subTest(event=event):
                args = self._args("--facility-event", event)
                with self.assertRaises(ValueError):
                    emergency.make_scenario(args, emergency.EmergencyCase(10, 42))

    def test_nonfinite_alarm_delay_is_rejected(self) -> None:
        args = self._args("--alarm-delay-seconds", "nan")

        with self.assertRaisesRegex(ValueError, "finite"):
            emergency.make_scenario(args, emergency.EmergencyCase(10, 42))

    def test_jupedsim_desired_speed_changes_physical_clearance(self) -> None:
        slow = emergency.run_case(
            self._args(
                "--populations",
                "5",
                "--minutes",
                "8",
                "--max-clearance-seconds",
                "480",
                "--jupedsim-desired-speed-mps",
                "0.6",
            ),
            emergency.EmergencyCase(5, 42),
        )
        fast = emergency.run_case(
            self._args(
                "--populations",
                "5",
                "--minutes",
                "8",
                "--max-clearance-seconds",
                "480",
                "--jupedsim-desired-speed-mps",
                "1.8",
            ),
            emergency.EmergencyCase(5, 42),
        )

        self.assertGreater(slow["clearance_time_seconds"], fast["clearance_time_seconds"])

    def test_density_slowdown_changes_physical_evacuation_outcome(self) -> None:
        free_flow = emergency.run_case(
            self._args(
                "--populations",
                "20",
                "--minutes",
                "8",
                "--max-clearance-seconds",
                "480",
                "--density-slowdown-strength",
                "0",
            ),
            emergency.EmergencyCase(20, 42),
        )
        slowed = emergency.run_case(
            self._args(
                "--populations",
                "20",
                "--minutes",
                "8",
                "--max-clearance-seconds",
                "480",
                "--density-slowdown-strength",
                "1",
            ),
            emergency.EmergencyCase(20, 42),
        )

        # Bottleneck evacuation is not monotone in free speed: moderating the
        # approach flow can reduce conflicts and produce a slower-is-faster
        # outcome.  This contract verifies that the density term reaches the
        # physical simulation without encoding the wrong directional law.
        self.assertNotEqual(
            slowed["mean_evacuation_duration_seconds"],
            free_flow["mean_evacuation_duration_seconds"],
        )

    def test_resume_requires_matching_configuration_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            args = self._args("--out-dir", directory)
            case = emergency.EmergencyCase(10, 42)
            row = {"run_id": case.run_id, "status": "ok", "acceptance_status": "pass"}
            emergency.write_outputs(args, [case], [row])

            resumed = emergency.build_parser().parse_args(
                [
                    "--populations",
                    "10",
                    "--seeds",
                    "42",
                    "--minutes",
                    "6",
                    "--tick-seconds",
                    "1",
                    "--min-completion-rate",
                    "1",
                    "--max-clearance-seconds",
                    "360",
                    "--max-final-station-persons",
                    "0",
                    "--out-dir",
                    directory,
                    "--resume",
                ]
            )
            self.assertEqual([row], emergency.load_resume_rows(resumed))

            changed = emergency.build_parser().parse_args(
                ["--out-dir", directory, "--minutes", "7", "--resume"]
            )
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                emergency.load_resume_rows(changed)
            self.assertTrue(Path(directory, "metro_emergency_matrix.json").exists())


if __name__ == "__main__":
    unittest.main()
