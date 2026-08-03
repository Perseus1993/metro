from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_metro_stress_matrix as stress


class MetroStressMatrixTests(unittest.TestCase):
    def test_parse_lists_and_explicit_pairs(self) -> None:
        self.assertEqual((60, 120, 240), stress.parse_int_list("60,120,240"))
        self.assertEqual(((60, 30), (120, 90)), stress.parse_pairs("60:30,120:90"))

    def test_build_cases_crosses_flows_and_seeds(self) -> None:
        cases = stress.build_cases(
            entries=(60, 120),
            exits=(30,),
            seeds=(1, 2),
            pairs=None,
        )

        self.assertEqual(
            [
                stress.StressCase(60, 30, 1),
                stress.StressCase(60, 30, 2),
                stress.StressCase(120, 30, 1),
                stress.StressCase(120, 30, 2),
            ],
            cases,
        )

    def test_completion_threshold_parser_rejects_non_finite_and_outside_values(self) -> None:
        self.assertEqual(0.0, stress.unit_interval("0"))
        self.assertEqual(1.0, stress.unit_interval("1"))
        for value in ("-0.0001", "1.0001", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(stress.argparse.ArgumentTypeError):
                    stress.unit_interval(value)

    def test_acceptance_thresholds_include_exact_boundary_and_reject_just_over_it(self) -> None:
        row = {
            "status": "ok",
            "spawned_persons": 10,
            "completion_rate": 0.8,
            "station_persons_final": 2,
        }

        exact = stress.assess_stress_row(
            row,
            min_completion_rate=0.8,
            max_final_station_persons=2,
        )
        completion_fail = stress.assess_stress_row(
            row,
            min_completion_rate=0.8001,
            max_final_station_persons=2,
        )
        backlog_fail = stress.assess_stress_row(
            row,
            min_completion_rate=0.8,
            max_final_station_persons=1,
        )

        self.assertEqual("pass", exact["acceptance_status"])
        self.assertEqual("fail", completion_fail["acceptance_status"])
        self.assertEqual("fail", backlog_fail["acceptance_status"])
        self.assertIn("completion rate", completion_fail["acceptance_issues"][0])
        self.assertIn("backlog", backlog_fail["acceptance_issues"][0])

    def test_production_preflight_requires_explicit_ready_configuration(self) -> None:
        default_args = stress.build_parser().parse_args(
            ["--pairs", "0:0", "--minutes", "2", "--demand-minutes", "1"]
        )
        ready_args = stress.build_parser().parse_args(
            [
                "--pairs",
                "0:0",
                "--minutes",
                "2",
                "--demand-minutes",
                "1",
                "--clock-mode",
                "physical",
                "--goal-graph-mode",
                "active",
                "--calibration-status",
                "validated",
                "--calibration-dataset-id",
                "calibration_day",
                "--validation-dataset-id",
                "validation_day",
                "--min-completion-rate",
                "1",
                "--production-acceptance",
            ]
        )
        case = stress.StressCase(entry_count_hour=0, exit_count_hour=0, seed=42)

        default_issues = stress.production_preflight_issues(default_args, case)
        ready_issues = stress.production_preflight_issues(ready_args, case)

        self.assertGreater(len(default_issues), 0)
        self.assertEqual([], ready_issues)
        ready_scenario = stress.make_scenario(ready_args, case)
        self.assertEqual("physical", ready_scenario.simulation_clock_mode)
        self.assertEqual("active", ready_scenario.goal_graph_mode)
        self.assertTrue(ready_scenario.calibration_profile.research_ready)

    def test_fault_configuration_disables_known_facility_and_records_train_controls(self) -> None:
        facility_id = "entry_gate:gate_bank_a:lane_1"
        args = stress.build_parser().parse_args(
            [
                "--pairs",
                "0:0",
                "--design-template",
                "visual_demo_station",
                "--disable-facility",
                facility_id,
                "--initial-train-offset-seconds",
                "600",
                "--train-headway-seconds",
                "300",
                "--train-dwell-seconds",
                "20",
                "--train-capacity-persons",
                "30",
            ]
        )
        case = stress.StressCase(entry_count_hour=0, exit_count_hour=0, seed=42)
        scenario = stress.make_scenario(args, case)
        model = stress.MetroStationModel(scenario, seed=42)

        disabled = model.facilities_by_id[facility_id]
        self.assertFalse(disabled.is_available_for_choice)
        self.assertEqual((facility_id,), scenario.disabled_facility_ids)
        self.assertEqual(600, scenario.initial_train_offset_seconds)
        self.assertEqual(300, scenario.train_headway_seconds)
        self.assertEqual(20, scenario.train_dwell_seconds)
        self.assertEqual(30, scenario.train_capacity_persons)
        facility_snapshot = next(
            item
            for item in model.snapshot()["facilities"]
            if item["id"] == facility_id
        )
        self.assertEqual("disabled", facility_snapshot["state"])

    def test_unknown_disabled_facility_fails_at_model_startup(self) -> None:
        args = stress.build_parser().parse_args(
            ["--pairs", "0:0", "--disable-facility", "missing:facility"]
        )
        case = stress.StressCase(entry_count_hour=0, exit_count_hour=0, seed=42)

        with self.assertRaisesRegex(ValueError, "unknown facilities"):
            stress.MetroStationModel(stress.make_scenario(args, case), seed=42)

    def test_all_disabled_entry_gates_contain_passengers_without_false_boarding(self) -> None:
        disabled_args = [
            value
            for lane in range(1, 7)
            for value in (
                "--disable-facility",
                f"entry_gate:gate_bank_a:lane_{lane}",
            )
        ]
        args = stress.build_parser().parse_args(
            [
                "--pairs",
                "600:0",
                "--minutes",
                "4",
                "--demand-minutes",
                "1",
                "--design-template",
                "visual_demo_station",
                "--movement-backend",
                "batched_jupedsim",
                "--clock-mode",
                "physical",
                "--goal-graph-mode",
                "active",
                "--min-completion-rate",
                "1",
                *disabled_args,
            ]
        )
        case = stress.StressCase(entry_count_hour=600, exit_count_hour=0, seed=42)

        row = stress.run_case(args, case)

        disabled = [
            item for item in row["final_facility_service"] if item["state"] == "disabled"
        ]
        self.assertEqual(0, row["boarded_persons"])
        self.assertEqual(row["spawned_persons"], row["station_persons_final"])
        self.assertEqual(6, len(disabled))
        self.assertEqual(0, sum(item["served_persons"] for item in disabled))

    def test_aggregate_summary_counts_acceptance_failures(self) -> None:
        rows = [
            {
                "status": "ok",
                "acceptance_status": "pass",
                "station_persons_final": 0,
                "station_persons_max": 1,
            },
            {
                "status": "ok",
                "acceptance_status": "fail",
                "station_persons_final": 3,
                "station_persons_max": 4,
            },
            {
                "status": "ok",
                "acceptance_status": "not_evaluated",
                "station_persons_final": 1,
                "station_persons_max": 2,
            },
        ]

        summary = stress.aggregate_summary(rows)

        self.assertEqual(1, summary["acceptance_passed"])
        self.assertEqual(1, summary["acceptance_failed"])
        self.assertEqual(1, summary["acceptance_not_evaluated"])

    def test_summarize_run_uses_final_and_max_frame_metrics(self) -> None:
        args = stress.build_parser().parse_args(
            [
                "--minutes",
                "2",
                "--entries",
                "60",
                "--exits",
                "60",
                "--design-template",
                "single_level_terminal",
            ]
        )
        case = stress.StressCase(entry_count_hour=60, exit_count_hour=60, seed=7)
        frames = [
            {
                "metrics": {
                    "station_persons": 1,
                    "gate_queue_persons": 0,
                    "vertical_queue_persons": 0,
                    "door_queue_persons": 0,
                    "platform_waiting_persons": 0,
                    "crowding_index": 0.2,
                    "average_walk_speed_factor": 1.0,
                }
            },
            {
                "metrics": {
                    "station_persons": 3,
                    "gate_queue_persons": 2,
                    "vertical_queue_persons": 1,
                    "door_queue_persons": 4,
                    "platform_waiting_persons": 5,
                    "spawned_persons": 4,
                    "spawned_entry_persons": 2,
                    "spawned_exit_persons": 2,
                    "boarded_persons": 1,
                    "exit_gate_served_persons": 1,
                    "average_system_minutes": 0.5,
                    "crowding_index": 1.4,
                    "average_walk_speed_factor": 0.75,
                    "movement_backend": "FakeBackend",
                    "jupedsim_operational_model": "social_force",
                    "jupedsim_steps": 12,
                    "jupedsim_batches": 3,
                    "audit_counts": {"debug": 2},
                },
                "passengers": [
                    {
                        "id": 1,
                        "intent": "enter_and_board",
                        "state": "queueing_door",
                        "n": 2,
                        "x": 10.5,
                        "y": 20.5,
                        "current_level_id": "b2_platform",
                        "goal": {"kind": "queued", "target": [11.0, 21.0]},
                        "behavior": {
                            "target_region": "boarding_door",
                            "facility_id": "boarding_door:1",
                            "queue_mode": "enqueued",
                            "distance_to_target": 0.5,
                            "progress_age_seconds": 25.0,
                            "last_replan_reason": "queue_wait_threshold",
                        },
                    },
                    {"id": 2, "intent": "exit_station", "state": "walking_to_exit_gate", "n": 1},
                ],
                "facilities": [
                    {
                        "id": "boarding_door:1",
                        "kind": "train_door",
                        "state": "open",
                        "queue_persons": 2,
                        "active_persons": 0,
                        "served_persons": 7,
                    }
                ],
                "trains": [
                    {
                        "current_load_persons": 3,
                        "last_departed_load_persons": 4,
                        "departed_trains": 2,
                    }
                ],
            },
        ]

        row = stress.summarize_run(args=args, case=case, frames=frames, elapsed_seconds=0.12345)

        self.assertEqual("ok", row["status"])
        self.assertEqual("entry_60_exit_60_seed_7", row["run_id"])
        self.assertEqual(2, row["completed_persons"])
        self.assertEqual(0.5, row["completion_rate"])
        self.assertEqual(3, row["station_persons_max"])
        self.assertEqual(4, row["door_queue_persons_max"])
        self.assertEqual(3, row["train_load_persons_max"])
        self.assertEqual(4, row["train_departed_load_persons_max"])
        self.assertEqual(2, row["departed_trains_final"])
        self.assertEqual(0.75, row["average_walk_speed_factor_min"])
        self.assertEqual("FakeBackend", row["movement_backend"])
        self.assertEqual("social_force", row["jupedsim_operational_model"])
        self.assertEqual(
            {"queueing_door": 2, "walking_to_exit_gate": 1},
            row["final_state_persons"],
        )
        self.assertEqual(2, row["final_facility_backlogs"][0]["queue_persons"])
        self.assertEqual(7, row["final_facility_service"][0]["served_persons"])
        self.assertEqual(1, row["final_passenger_samples"][0]["id"])
        self.assertEqual(25.0, row["final_passenger_samples"][0]["progress_age_seconds"])
        self.assertEqual(
            "queue_wait_threshold",
            row["final_passenger_samples"][0]["last_replan_reason"],
        )

    def test_run_matrix_checkpoints_after_each_completed_case(self) -> None:
        args = stress.build_parser().parse_args(["--pairs", "60:0", "--quiet"])
        cases = [
            stress.StressCase(entry_count_hour=60, exit_count_hour=0, seed=1),
            stress.StressCase(entry_count_hour=60, exit_count_hour=0, seed=2),
        ]
        completed_counts: list[int] = []

        with patch.object(
            stress,
            "run_case",
            side_effect=[
                {"status": "ok", "acceptance_status": "pass"},
                {"status": "ok", "acceptance_status": "pass"},
            ],
        ):
            rows = stress.run_matrix(
                args,
                cases,
                checkpoint=lambda partial: completed_counts.append(len(partial)),
            )

        self.assertEqual(2, len(rows))
        self.assertEqual([1, 2], completed_counts)

    def test_write_outputs_creates_csv_json_and_markdown(self) -> None:
        args = stress.build_parser().parse_args(["--entries", "60", "--exits", "60"])
        case = stress.StressCase(entry_count_hour=60, exit_count_hour=60, seed=42)
        row = {field: None for field in stress.FIELDNAMES}
        row.update(
            {
                "run_id": case.run_id,
                "status": "ok",
                "entry_count_hour": 60,
                "exit_count_hour": 60,
                "seed": 42,
                "spawned_persons": 2,
                "completed_persons": 1,
                "station_persons_final": 1,
                "station_persons_max": 2,
                "audit_counts": {"debug": 1},
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = stress.OutputPaths(
                csv_path=stress.Path(tmp_dir) / "matrix.csv",
                json_path=stress.Path(tmp_dir) / "matrix.json",
                markdown_path=stress.Path(tmp_dir) / "matrix.md",
            )

            stress.write_outputs(paths, args=args, cases=[case], rows=[row])

            self.assertIn("entry_count_hour", paths.csv_path.read_text(encoding="utf-8"))
            json_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, json_payload["summary"]["ok"])
            self.assertEqual(case.run_id, json_payload["runs"][0]["run_id"])
            markdown_text = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Metro Stress Matrix Summary", markdown_text)
            self.assertIn(case.run_id, paths.csv_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
