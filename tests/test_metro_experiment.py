from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from sandbox.metro_station_sandbox.design import create_design
from metro_station_experiments.diagnosis import (
    TrajectoryReport,
    diagnostic_truth_payload,
    diagnose_tracks,
)
from metro_station_experiments.report import write_experiment_report
from metro_station_experiments.runner import (
    ExperimentCase,
    ExperimentRunner,
    build_cases,
    load_design_file,
    scenario_from_case,
)
from scripts.analyze_metro_tracks import analyze_tracks


class MetroExperimentTests(unittest.TestCase):
    def test_runner_executes_single_case_and_diagnoses_tracks(self) -> None:
        case = ExperimentCase(
            case_id="single_smoke",
            design=create_design("single_level_terminal"),
            design_label="single_level_terminal",
            entry_count_hour=60,
            exit_count_hour=0,
            seed=42,
            minutes=1,
        )

        result = ExperimentRunner([case]).run_all()[0]

        self.assertEqual("ok", result.status, result.error)
        self.assertGreater(len(result.frames), 0)
        self.assertIn("spawned_persons", result.metrics)
        self.assertIsNotNone(result.tracks_payload)
        self.assertIsNotNone(result.trajectory_report)
        self.assertIn(result.trajectory_report.pass_fail, {"pass", "warn", "fail"})
        self.assertIn("facility_samples", result.tracks_payload)
        self.assertGreater(len(result.tracks_payload["facility_samples"]), 0)
        self.assertEqual("visualization_bundle.v1", result.tracks_payload["schema_version"])
        self.assertEqual(
            "simulation_trace.v1",
            result.tracks_payload["simulation_trace"]["schema_version"],
        )
        self.assertIn("derived", result.tracks_payload)
        self.assertIn("visualization_bundle", result.tracks_payload)
        replay_package = result.tracks_payload["replay_package"]
        self.assertEqual("replay_package.v2", replay_package["schema_version"])
        self.assertEqual("station_scene.v1", replay_package["station_scene"]["schema_version"])
        self.assertEqual("asset_manifest.v1", replay_package["asset_manifest"]["schema_version"])
        self.assertEqual("#/simulation_trace", replay_package["simulation_trace_ref"])
        self.assertEqual("#/visualization_bundle", replay_package["visualization_bundle_ref"])

    def test_runner_exports_gate_events_and_visual_waypoints(self) -> None:
        case = ExperimentCase(
            case_id="gate_visual_smoke",
            design=create_design("visual_demo_station"),
            design_label="visual_demo_station",
            entry_count_hour=120,
            exit_count_hour=0,
            seed=42,
            minutes=3,
            tick_seconds=5,
        )

        result = ExperimentRunner([case]).run_case(case)

        self.assertEqual("ok", result.status, result.error)
        self.assertIsNotNone(result.tracks_payload)
        gate_events = result.tracks_payload.get("gate_events", [])
        self.assertGreater(len(gate_events), 0)
        gate_passenger_id = gate_events[0]["passenger_ids"][0]
        gate_track = next(
            agent for agent in result.tracks_payload["agents"] if agent["id"] == gate_passenger_id
        )
        self.assertTrue(
            any(float(point[0]) % case.tick_seconds for point in gate_track["presentation_points"])
        )
        visual_only_points = [
            point
            for point in gate_track["presentation_points"]
            if len(point) > 9 and isinstance(point[9], dict) and point[9].get("visual_only")
        ]
        self.assertGreater(len(visual_only_points), 0)
        self.assertTrue(all(not point[9]["visual_only"] for point in gate_track["points"]))

    def test_diagnostic_truth_payload_filters_visual_only_points(self) -> None:
        payload = {
            "agents": [
                {
                    "id": 1,
                    "presentation_points": [[1.0, 100.0, 0.0]],
                    "points": [
                        [0.0, 0.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"source": "simulation", "visual_only": False}],
                        [1.0, 100.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"source": "interpolation", "visual_only": True}],
                        [2.0, 2.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"source": "simulation", "visual_only": False}],
                    ],
                }
            ],
            "visualization_bundle": {
                "visual_tracks": [
                    {
                        "id": 1,
                        "points": [
                            [0.0, 0.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"source": "simulation", "visual_only": False}],
                            [1.0, 100.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"source": "interpolation", "visual_only": True}],
                        ],
                    }
                ]
            },
        }

        sanitized = diagnostic_truth_payload(payload)

        self.assertEqual([0.0, 2.0], [point[0] for point in sanitized["agents"][0]["points"]])
        self.assertTrue(all(len(point) == 9 for point in sanitized["agents"][0]["points"]))
        self.assertNotIn("presentation_points", sanitized["agents"][0])

    def test_legacy_track_analyzer_filters_visual_only_points(self) -> None:
        payload = {
            "agents": [
                {
                    "id": 1,
                    "route": "enter_and_board",
                    "source": "unit",
                    "points": [
                        [0.0, 0.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"visual_only": False}],
                        [1.0, 100.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"visual_only": True}],
                        [2.0, 2.0, 0.0, 0.0, 1.0, None, None, "targeting", "target", {"visual_only": False}],
                    ],
                }
            ]
        }

        report = analyze_tracks(payload)

        self.assertEqual(1, report["movement"]["overall"]["total_segments"])
        self.assertEqual(2.0, report["movement"]["overall"]["total_distance_px"])

    def test_diagnosis_prefers_simulation_trace_over_visual_anomalies(self) -> None:
        payload = _truth_payload(
            spawned=1,
            completed=1,
            remaining=0,
            final_passengers=[],
        )
        payload["layout"] = {
            "connector_channels": [
                {
                    "id": "vertical",
                    "kind": "escalator",
                    "direction": "down",
                    "width_px": 120,
                    "line": [[0, 0], [1000, 0]],
                }
            ],
            "decision_regions": [],
        }
        payload["agents"] = [
            {
                "id": 1,
                "route": "enter_and_board",
                "source": "unit",
                "points": [
                    [0.0, 0.0, 0.0, 0.0, 1.0, None, None, "targeting", "target"],
                    [1.0, 900.0, 0.0, 0.0, 1.0, None, None, "targeting", "target"],
                ],
            }
        ]

        report = diagnose_tracks(payload)

        self.assertEqual("simulation_trace", report.diagnosis_source)
        self.assertEqual("pass", report.pass_fail)
        self.assertEqual(1.0, report.completion_rate)
        self.assertGreater(report.visual_checks["anomaly_count"], 0)
        self.assertEqual(0, report.anomaly_count)

    def test_diagnosis_uses_simulation_trace_completion_over_clearance_payload(self) -> None:
        payload = _truth_payload(
            spawned=10,
            completed=5,
            remaining=5,
            final_passengers=[
                {"id": index, "state": "waiting_platform"}
                for index in range(6, 11)
            ],
        )
        payload["clearance_audit"] = {
            "completed_agents": 10,
            "remaining_agents": 0,
            "total_agents": 10,
        }

        report = diagnose_tracks(payload)

        self.assertEqual("simulation_trace", report.diagnosis_source)
        self.assertEqual(0.5, report.completion_rate)
        self.assertEqual(5, report.stuck_agents)
        self.assertEqual("fail", report.pass_fail)

    def test_runner_reports_progress_steps(self) -> None:
        case = ExperimentCase(
            case_id="progress_smoke",
            design=create_design("single_level_terminal"),
            design_label="single_level_terminal",
            entry_count_hour=30,
            exit_count_hour=0,
            seed=42,
            minutes=1,
            tick_seconds=10,
        )
        updates: list[tuple[int, int]] = []

        result = ExperimentRunner([case]).run_case(
            case,
            progress_callback=lambda step, total: updates.append((step, total)),
        )

        self.assertEqual("ok", result.status, result.error)
        self.assertGreater(len(updates), 1)
        self.assertEqual(0, updates[0][0])
        self.assertEqual(updates[-1][1], updates[-1][0])
        self.assertGreater(updates[-1][1], 0)

    def test_report_writes_multi_case_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            results = [
                _fake_result("scheme_a", "pass", completion_rate=0.95, remaining=1),
                _fake_result("scheme_b", "fail", completion_rate=0.50, remaining=20),
            ]

            write_experiment_report(results, output_dir)

            markdown = (output_dir / "experiment_report.md").read_text(encoding="utf-8")
            payload = json.loads(
                (output_dir / "experiment_results.json").read_text(encoding="utf-8")
            )
            tracks_exists = (output_dir / "scheme_a_tracks.js").exists()

        self.assertIn("scheme_a", markdown)
        self.assertIn("scheme_b", markdown)
        self.assertTrue(tracks_exists)
        self.assertEqual(2, len(payload["results"]))
        self.assertEqual("scheme_a_tracks.js", payload["results"][0]["replay_file"])
        self.assertEqual("fail", payload["results"][1]["trajectory_report"]["pass_fail"])

    def test_report_can_write_replay_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "report"
            asset_dir = Path(tmp_dir) / "assets" / "experiment_tracks"

            write_experiment_report(
                [_fake_result("scheme_a", "pass", completion_rate=0.95, remaining=1)],
                output_dir,
                replay_asset_dir=asset_dir,
                replay_url_prefix="assets/experiment_tracks",
            )

            payload = json.loads(
                (output_dir / "experiment_results.json").read_text(encoding="utf-8")
            )
            replay_asset_exists = (asset_dir / "scheme_a_tracks.js").exists()

        self.assertTrue(replay_asset_exists)
        self.assertEqual(
            "assets/experiment_tracks/scheme_a_tracks.js",
            payload["results"][0]["replay_file"],
        )

    def test_design_file_loader_accepts_compile_payload(self) -> None:
        document = create_design("single_level_terminal")
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "draft.json"
            path.write_text(
                json.dumps({"document": document.as_dict()}, ensure_ascii=False),
                encoding="utf-8",
            )

            loaded = load_design_file(path)

        self.assertEqual(document.id, loaded.id)
        self.assertEqual(len(document.elements), len(loaded.elements))

    def test_build_cases_expands_design_demand_seed_product(self) -> None:
        document = create_design("single_level_terminal")

        cases = build_cases(
            designs=(("single", document), ("single_copy", document)),
            entries=(60, 120),
            exits=(0,),
            transfers=(0,),
            seeds=(1, 2),
            minutes=1,
            tick_seconds=5,
            group_size=1,
            movement_backend="batched_jupedsim",
            jupedsim_model="collision_free_speed",
            station_name="unit",
            hour=18,
        )

        self.assertEqual(8, len(cases))
        self.assertEqual(
            "single_entry_60_exit_0_seed_1",
            cases[0].case_id,
        )

    def test_build_cases_can_expand_transfer_demand(self) -> None:
        document = create_design("single_level_terminal")

        cases = build_cases(
            designs=(("single", document),),
            entries=(0,),
            exits=(0,),
            transfers=(60, 120),
            seeds=(1,),
            minutes=1,
            tick_seconds=5,
            group_size=1,
            movement_backend="batched_jupedsim",
            jupedsim_model="collision_free_speed",
            station_name="unit",
            hour=18,
        )

        self.assertEqual(2, len(cases))
        self.assertEqual(60, cases[0].transfer_count_hour)
        self.assertEqual("single_entry_0_exit_0_transfer_60_seed_1", cases[0].case_id)

    def test_case_operations_flow_into_scenario(self) -> None:
        case = ExperimentCase(
            case_id="ops",
            design=create_design("single_level_terminal"),
            design_label="single",
            entry_count_hour=60,
            exit_count_hour=0,
            transfer_count_hour=30,
            operations={
                "gate_service_persons_per_min": 7,
                "train_dwell_seconds": 9,
                "walk_units_per_tick": 1.25,
            },
        )

        scenario = scenario_from_case(case)

        self.assertEqual(7, scenario.gate_service_persons_per_min)
        self.assertEqual(9, scenario.train_dwell_seconds)
        self.assertEqual(1.25, scenario.walk_units_per_tick)
        self.assertEqual(30, scenario.transfer_count_hour)


def _fake_result(
    case_id: str,
    pass_fail: str,
    *,
    completion_rate: float,
    remaining: int,
) -> SimpleNamespace:
    case = SimpleNamespace(
        case_id=case_id,
        design_label=case_id,
        entry_count_hour=1000,
        exit_count_hour=500,
        seed=42,
        minutes=3,
        movement_backend="batched_jupedsim",
    )
    trajectory_report = TrajectoryReport(
        stationary_agents=0,
        stationary_duration_share=0.0,
        slow_agents=0,
        bottleneck_cells=[],
        reverse_segments=0,
        teleport_segments=0,
        stuck_agents=0 if pass_fail != "fail" else 2,
        anomaly_count=0,
        target_jump_count=0,
        far_jump_count=0,
        completion_rate=completion_rate,
        pass_fail=pass_fail,
        issues=[] if pass_fail == "pass" else ["synthetic issue"],
        analysis_errors={},
    )
    return SimpleNamespace(
        case=case,
        status="ok",
        metrics={
            "station_persons": remaining,
            "average_system_minutes": 1.25,
            "gate_queue_persons": 4,
            "vertical_queue_persons": 7,
        },
        tracks_payload={
            "clearance_audit": {
                "remaining_agents": remaining,
                "completed_agents": 10,
                "total_agents": 10 + remaining,
            },
            "agents": [{"id": 1}],
        },
        trajectory_report=trajectory_report,
        error=None,
        frames=[{"time_seconds": 0.0}],
    )


def _truth_payload(
    *,
    spawned: int,
    completed: int,
    remaining: int,
    final_passengers: list[dict[str, object]],
) -> dict[str, object]:
    metrics = {
        "spawned_persons": spawned,
        "boarded_persons": completed,
        "exit_gate_served_persons": 0,
        "station_persons": remaining,
    }
    return {
        "duration": 5.0,
        "clearance_audit": {
            "completed_agents": completed,
            "remaining_agents": remaining,
            "total_agents": spawned,
        },
        "simulation_trace": {
            "schema_version": "simulation_trace.v1",
            "run_id": "unit",
            "metadata": {},
            "snapshots": [
                {
                    "step": 0,
                    "time_seconds": 0.0,
                    "passengers": [{"id": 1, "state": "entering_station"}],
                    "facilities": [],
                    "metrics": metrics,
                },
                {
                    "step": 1,
                    "time_seconds": 5.0,
                    "passengers": final_passengers,
                    "facilities": [],
                    "metrics": metrics,
                },
            ],
            "facility_events": [
                {
                    "event_id": 1,
                    "facility_id": "boarding_door:1",
                    "facility_kind": "train_door",
                    "mode": None,
                    "passenger_ids": [1],
                    "start_time": 1.0,
                    "board_end_time": None,
                    "arrive_time": None,
                    "end_time": 2.0,
                }
            ],
            "aggregate_metrics": metrics,
        },
    }


if __name__ == "__main__":
    unittest.main()
