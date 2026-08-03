from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_vertical_trajectories import TrajectoryConfig, build_report, main


class VerticalTrajectoryAnalysisTests(unittest.TestCase):
    def sample_payload(self, points: list[list[object]], *, direction: str = "down") -> dict[str, object]:
        return {
            "generated_by": "unit",
            "duration": 30.0,
            "layout": {
                "connector_channels": [
                    {
                        "id": "down_escalator",
                        "kind": "escalator",
                        "direction": direction,
                        "width_px": 20,
                        "line": [[0.1, 0.1], [0.9, 0.1]],
                    },
                    {
                        "id": "elevator_shaft",
                        "kind": "elevator",
                        "direction": "both",
                        "width_px": 20,
                        "line": [[0.2, 0.2], [0.2, 0.8]],
                    },
                ]
            },
            "agents": [
                {
                    "id": "a1",
                    "route": "enter_and_board",
                    "route_chain": ["enter_and_board", "vertical"],
                    "source": "unit",
                    "points": points,
                }
            ],
        }

    def config(self) -> TrajectoryConfig:
        return TrajectoryConfig(
            kinds=("elevator", "escalator"),
            canvas_width=100.0,
            canvas_height=100.0,
            px_per_meter=10.0,
            stuck_seconds=20.0,
            top_n=10,
        )

    def test_normal_escalator_progress_has_no_anomalies(self) -> None:
        report = build_report(
            self.sample_payload(
                [
                    [0.0, 10.0, 10.0, 0.0, 1.0],
                    [5.0, 50.0, 10.0, 0.0, 1.0],
                    [10.0, 90.0, 10.0, 0.0, 1.0],
                ]
            ),
            input_path=Path("unit.js"),
            config=self.config(),
        )

        self.assertEqual("ok", report["summary"]["status"])
        self.assertEqual(2, report["summary"]["connector_segments"])
        self.assertEqual(0, report["summary"]["reverse_segments"])
        self.assertEqual(0, report["summary"]["jump_or_speed_segments"])

    def test_reverse_escalator_progress_is_reported(self) -> None:
        report = build_report(
            self.sample_payload(
                [
                    [0.0, 90.0, 10.0, 0.0, 1.0],
                    [5.0, 50.0, 10.0, 0.0, 1.0],
                    [10.0, 10.0, 10.0, 0.0, 1.0],
                ]
            ),
            input_path=Path("unit.js"),
            config=self.config(),
        )

        self.assertEqual("review", report["summary"]["status"])
        self.assertEqual(2, report["summary"]["reverse_segments"])
        self.assertEqual("reverse", report["anomalies"][0]["issue"])

    def test_stairs_service_event_is_not_misclassified_as_adjacent_escalator_reverse(self) -> None:
        payload = self.sample_payload(
            [
                [0.0, 90.0, 10.0, 0.0, 1.0],
                [5.0, 50.0, 10.0, 0.0, 1.0],
                [10.0, 10.0, 10.0, 0.0, 1.0],
            ]
        )
        payload["vertical_service_events"] = [
            {
                "facility_id": "vertical:stairs_a:down:b1:b2",
                "facility_kind": "stairs",
                "passenger_ids": ["a1"],
                "start_time": 0.0,
                "end_time": 10.0,
                "direction": "down",
                "start_canvas": [90.0, 12.0],
                "end_canvas": [10.0, 12.0],
            }
        ]

        report = build_report(payload, input_path=Path("unit.js"), config=self.config())

        self.assertEqual(2, report["summary"]["service_event_segments"])
        self.assertEqual(0, report["summary"]["reverse_segments"])
        self.assertEqual("ok", report["summary"]["status"])

    def test_fast_jump_inside_connector_is_reported(self) -> None:
        report = build_report(
            self.sample_payload(
                [
                    [0.0, 10.0, 10.0, 0.0, 1.0],
                    [1.0, 95.0, 10.0, 0.0, 1.0],
                ]
            ),
            input_path=Path("unit.js"),
            config=self.config(),
        )

        self.assertEqual(1, report["summary"]["jump_or_speed_segments"])
        self.assertEqual("jump_or_speed", report["anomalies"][0]["issue"])

    def test_stationary_elevator_agent_is_reported_as_stuck(self) -> None:
        report = build_report(
            self.sample_payload(
                [
                    [0.0, 20.0, 20.0, 0.0, 1.0],
                    [10.0, 20.0, 20.0, 0.0, 1.0],
                    [20.0, 20.0, 20.0, 0.0, 1.0],
                    [30.0, 20.0, 20.0, 0.0, 1.0],
                ]
            ),
            input_path=Path("unit.js"),
            config=self.config(),
        )

        self.assertEqual(1, report["summary"]["stuck_agents"])
        self.assertEqual("stuck_in_connector", report["anomalies"][0]["issue"])

    def test_stationary_queue_wait_inside_connector_is_not_stuck(self) -> None:
        report = build_report(
            self.sample_payload(
                [
                    [0.0, 20.0, 20.0, 0.0, 1.0, 20.0, 20.0, "enqueued", "queue"],
                    [10.0, 20.0, 20.0, 0.0, 1.0, 20.0, 20.0, "enqueued", "queue"],
                    [20.0, 20.0, 20.0, 0.0, 1.0, 20.0, 20.0, "enqueued", "queue"],
                    [30.0, 20.0, 20.0, 0.0, 1.0, 20.0, 20.0, "enqueued", "queue"],
                ]
            ),
            input_path=Path("unit.js"),
            config=self.config(),
        )

        self.assertEqual("ok", report["summary"]["status"])
        self.assertEqual(0, report["summary"]["stuck_agents"])

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "tracks.js"
            json_out = tmp_path / "report.json"
            markdown_out = tmp_path / "report.md"
            input_path.write_text(
                "window.JPS_TRACKS = "
                + json.dumps(
                    self.sample_payload(
                        [
                            [0.0, 10.0, 10.0, 0.0, 1.0],
                            [5.0, 50.0, 10.0, 0.0, 1.0],
                        ]
                    ),
                    separators=(",", ":"),
                )
                + ";\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        str(input_path),
                        "--json-out",
                        str(json_out),
                        "--markdown-out",
                        str(markdown_out),
                        "--canvas-width",
                        "100",
                        "--canvas-height",
                        "100",
                        "--px-per-meter",
                        "10",
                    ]
                )

            self.assertEqual(0, code)
            self.assertIn("connector_segments=1", stdout.getvalue())
            self.assertEqual(
                1,
                json.loads(json_out.read_text(encoding="utf-8"))["summary"][
                    "connector_segments"
                ],
            )
            self.assertIn(
                "Vertical Connector Trajectory Diagnostics",
                markdown_out.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
