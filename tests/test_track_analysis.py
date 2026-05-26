from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_metro_tracks import (
    AnalysisConfig,
    build_report,
    main,
    parse_jps_tracks_text,
)


class TrackAnalysisTests(unittest.TestCase):
    def sample_payload(self) -> dict[str, object]:
        return {
            "generated_by": "unit",
            "duration": 10.0,
            "agents": [
                {
                    "id": 1,
                    "route": "enter_and_board",
                    "source": "unit",
                    "points": [
                        [0.0, 0.0, 0.0, 0.0, 1.0],
                        [5.0, 0.0, 0.0, 0.0, 1.0],
                        [10.0, 20.0, 0.0, 0.0, 1.0],
                    ],
                },
                {
                    "id": 2,
                    "route": "exit_station",
                    "source": "unit",
                    "points": [
                        [5.0, 40.0, 0.0, 0.0, 1.0],
                        [10.0, 40.0, 0.0, 0.0, 1.0],
                    ],
                },
            ],
            "queue_layouts": [
                {
                    "id": "entry_gate_queue",
                    "kind": "entry_gate",
                    "lanes": 2,
                    "capacity": 3,
                    "slots": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]],
                },
                {
                    "id": "boarding_queue",
                    "kind": "boarding",
                    "lanes": 1,
                    "capacity": 2,
                    "slots": [[0.4, 0.4], [0.5, 0.5]],
                },
            ],
            "queue_samples": [
                {
                    "time": 0.0,
                    "queues": {
                        "entry_gate_queue": {"enqueued": 1, "targeting": 2},
                        "boarding_queue": {"enqueued": 0, "targeting": 1},
                    },
                },
                {
                    "time": 5.0,
                    "queues": {
                        "entry_gate_queue": {"enqueued": 2, "targeting": 3},
                        "boarding_queue": {"enqueued": 1, "targeting": 1},
                    },
                },
            ],
        }

    def test_parse_window_assignment(self) -> None:
        payload = parse_jps_tracks_text('window.JPS_TRACKS = {"agents": []};\n')
        self.assertEqual({"agents": []}, payload)

    def test_report_includes_active_curve_slow_stats_bottlenecks_and_queues(self) -> None:
        report = build_report(
            self.sample_payload(),
            input_path=Path("unit.js"),
            config=AnalysisConfig(
                grid_size_px=50.0,
                slow_speed_m_s=0.30,
                stationary_speed_m_s=0.03,
                px_per_meter=20.0,
                top_n=5,
            ),
        )

        self.assertEqual(
            [
                {"time_s": 0.0, "active": 1},
                {"time_s": 5.0, "active": 2},
                {"time_s": 10.0, "active": 2},
            ],
            report["active_curve"]["points"],
        )
        movement = report["movement"]["overall"]
        self.assertEqual(3, movement["slow_segments"])
        self.assertEqual(2, movement["stationary_segments"])
        self.assertEqual(15.0, movement["slow_duration_s"])
        self.assertEqual(10.0, movement["stationary_duration_s"])

        top_cell = report["bottleneck_grid"]["top_cells"][0]
        self.assertEqual([0, 0], top_cell["cell"])
        self.assertEqual(25.0, top_cell["bottleneck_score_s"])
        self.assertEqual(2, top_cell["unique_agents"])

        layout_counts = report["queues"]["layout_counts"]
        self.assertEqual(2, layout_counts["queue_count"])
        self.assertEqual(5, layout_counts["total_capacity"])
        self.assertEqual(3, layout_counts["by_kind"]["entry_gate"]["capacity"])

        queue_peak = report["queues"]["sample_counts"]["top_queues"][0]
        self.assertEqual("entry_gate_queue", queue_peak["id"])
        self.assertEqual(5, queue_peak["max_total"])

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "tracks.js"
            json_out = tmp_path / "report.json"
            markdown_out = tmp_path / "report.md"
            input_path.write_text(
                "window.JPS_TRACKS = "
                + json.dumps(self.sample_payload(), separators=(",", ":"))
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
                        "--top",
                        "3",
                    ]
                )

            self.assertEqual(0, code)
            self.assertIn("peak_active=2", stdout.getvalue())
            self.assertEqual(
                2, json.loads(json_out.read_text(encoding="utf-8"))["summary"]["tracks"]
            )
            self.assertIn(
                "Metro Track Bottleneck Diagnostics",
                markdown_out.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
