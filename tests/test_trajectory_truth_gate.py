from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

from metro_station_acceptance.trajectory_truth_cli import main
from metro_station_acceptance.trajectory_truth_gate import (
    TRAJECTORY_TRUTH_GATE_SCHEMA_VERSION,
    TrajectoryTruthGateConfig,
    analyze_trajectory_truth,
)
from metro_station_acceptance.trajectory_truth_inputs import TrajectoryTruthInputError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trajectory_truth"


def _fixture(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _snapshot(time_s: float, *passengers: tuple[int, float, float]) -> dict[str, object]:
    return {
        "time_seconds": time_s,
        "passengers": [
            {"id": agent_id, "x": x, "y": y}
            for agent_id, x, y in passengers
        ],
    }


class TrajectoryTruthGateTests(unittest.TestCase):
    def test_normal_simulation_trace_passes_and_reports_sampling_distribution(self) -> None:
        report = analyze_trajectory_truth(_fixture("normal_trace.json"))

        self.assertEqual(TRAJECTORY_TRUTH_GATE_SCHEMA_VERSION, report["schema_version"])
        self.assertTrue(report["passed"])
        self.assertEqual("simulation_truth", report["source"]["authority"])
        self.assertEqual(0, report["source"]["visual_samples_accepted"])
        self.assertEqual(1.0, report["sampling_intervals_s"]["p50"])
        self.assertEqual(0.5, report["checks"]["average_speed_within_bound"]["observed_max_average_speed_m_s"])

    def test_current_double_t0_shape_fails_same_id_same_time_gate(self) -> None:
        report = analyze_trajectory_truth(_fixture("double_t0_failure.json"))

        check = report["checks"]["same_id_same_time_single_position"]
        self.assertFalse(report["passed"])
        self.assertEqual("fail", check["status"])
        self.assertEqual(2, check["count"])
        self.assertEqual(2, report["sampling_intervals_s"]["zero_count"])

    def test_direct_snapshot_array_is_a_supported_truth_input(self) -> None:
        report = analyze_trajectory_truth(
            [
                _snapshot(0.0, (1, 0.0, 0.0)),
                _snapshot(1.0, (1, 0.5, 0.0)),
            ]
        )

        self.assertTrue(report["passed"])
        self.assertEqual("simulation_trace.snapshots", report["source"]["kind"])
        self.assertEqual("m", report["source"]["coordinate_unit"])

    def test_long_exact_colocation_fails_for_synchronously_moving_pair(self) -> None:
        report = analyze_trajectory_truth(_fixture("long_colocation_failure.json"))

        check = report["checks"]["no_persistent_exact_colocation"]
        self.assertEqual("fail", check["status"])
        self.assertEqual(1, check["count"])
        self.assertEqual(2.0, check["examples"][0]["duration_s"])
        self.assertEqual(["10", "11"], check["examples"][0]["agent_ids"])

    def test_non_finite_time_regression_and_meter_speed_are_hard_failures(self) -> None:
        payload = {
            "coordinate_unit": "m",
            "points": [
                {"id": "a", "t": 0.0, "x": 0.0, "y": 0.0},
                {"id": "a", "t": 1.0, "x": 4.0, "y": 0.0},
                {"id": "a", "t": 0.5, "x": 4.1, "y": 0.0},
                {"id": "b", "t": 0.0, "x": math.nan, "y": 1.0},
            ],
        }

        report = analyze_trajectory_truth(payload)

        self.assertEqual("fail", report["checks"]["finite_time_and_coordinates"]["status"])
        self.assertEqual("fail", report["checks"]["strictly_non_regressing_time"]["status"])
        self.assertEqual("fail", report["checks"]["average_speed_within_bound"]["status"])

    def test_speed_gate_is_skipped_when_normalized_coordinates_have_unknown_unit(self) -> None:
        payload = {
            "points": [
                {"id": "a", "t": 0.0, "x": 0.0, "y": 0.0},
                {"id": "a", "t": 1.0, "x": 100.0, "y": 0.0},
            ]
        }

        report = analyze_trajectory_truth(payload)

        self.assertTrue(report["passed"])
        self.assertEqual("skipped", report["checks"]["average_speed_within_bound"]["status"])

    def test_replay_wrapper_uses_simulation_trace_and_direct_visual_input_is_rejected(self) -> None:
        wrapper = {
            "simulation_trace": {
                "schema_version": "simulation_trace.v1",
                "snapshots": [_snapshot(0.0, (1, 0.0, 0.0))],
            },
            "visualization_bundle": {"visual_tracks": [{"id": 1, "points": []}]},
        }

        report = analyze_trajectory_truth(wrapper)

        self.assertEqual("replay.simulation_trace", report["source"]["kind"])
        with self.assertRaisesRegex(TrajectoryTruthInputError, "presentation data"):
            analyze_trajectory_truth({"visual_tracks": [{"id": 1, "points": []}]})
        with self.assertRaisesRegex(TrajectoryTruthInputError, "visual_only"):
            analyze_trajectory_truth(
                {
                    "points": [
                        {
                            "id": 1,
                            "t": 0.0,
                            "x": 0.0,
                            "y": 0.0,
                            "meta": {"visual_only": True},
                        }
                    ]
                }
            )

    def test_cli_writes_versioned_failure_report_and_returns_one(self) -> None:
        payload = {
            "schema_version": "simulation_trace.v1",
            "snapshots": [
                _snapshot(0.0, (1, 0.0, 0.0)),
                _snapshot(0.0, (1, 1.0, 0.0)),
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "trace.json"
            output_path = Path(temp_dir) / "report.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            code = main([str(input_path), "--output", str(output_path)])
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(1, code)
        self.assertEqual(TRAJECTORY_TRUTH_GATE_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("fail", report["status"])

    def test_config_rejects_invalid_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            analyze_trajectory_truth(
                {"points": [{"id": 1, "t": 0.0, "x": 0.0, "y": 0.0}]},
                config=TrajectoryTruthGateConfig(min_exact_colocation_samples=1),
            )


if __name__ == "__main__":
    unittest.main()
