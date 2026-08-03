from __future__ import annotations

import json
import tempfile
import unittest
from math import hypot

from scripts import run_vertical_flow_probe as probe


class VerticalFlowProbeTests(unittest.TestCase):
    def test_parse_lists_and_arrival_schedule_profiles(self) -> None:
        self.assertEqual((120, 600, 1200), probe.parse_int_list("120,600,1200"))
        self.assertEqual(("escalator", "elevator"), probe.parse_str_list("escalator,elevator"))

        burst = probe.arrival_schedule(
            demand_hour=600,
            minutes=1,
            tick_seconds=5,
            group_size=1,
            profile="burst",
        )
        self.assertEqual({0: 10}, dict(burst))

        uniform = probe.arrival_schedule(
            demand_hour=600,
            minutes=1,
            tick_seconds=5,
            group_size=1,
            profile="uniform",
        )
        self.assertEqual(10, sum(uniform.values()))
        self.assertIn(0, uniform)

    def test_linear_runs_clear_small_flow_for_each_vertical_kind(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--kinds",
                "escalator,elevator,stairs",
                "--demands",
                "180",
                "--service-persons",
                "60",
                "--minutes",
                "1",
                "--tick-seconds",
                "1",
                "--drain-seconds",
                "180",
                "--walk-units-per-tick",
                "3.5",
                "--movement-backend",
                "linear",
            ]
        )

        for kind in ("escalator", "elevator", "stairs"):
            with self.subTest(kind=kind):
                case = probe.ProbeCase(
                    facility_kind=kind,
                    demand_hour=180,
                    service_persons_per_min=60,
                    seed=1,
                )

                row = probe.run_case(args, case)

                self.assertEqual("ok", row["status"])
                self.assertEqual("cleared", row["clearance"])
                self.assertEqual(3, row["source_persons"])
                self.assertEqual(row["source_persons"], row["served_persons"])
                self.assertEqual(row["source_persons"], row["sink_persons"])
                self.assertEqual(0, row["unserved_persons"])
                self.assertGreater(row["approach_persons_max"], 0)
                self.assertGreater(row["service_persons_max"], 0)

    def test_vertical_probe_queue_front_matches_service_entry(self) -> None:
        for kind in ("escalator", "elevator", "stairs"):
            with self.subTest(kind=kind):
                spec = probe.vertical_spec(
                    kind=kind,
                    service_persons_per_min=60,
                )

                self.assertEqual(spec.position, spec.queue_anchor)
                self.assertEqual(spec.position, spec.queue_layout.slot(0))

    def test_elevator_batches_do_not_exceed_cabin_capacity(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--kinds",
                "elevator",
                "--demands",
                "600",
                "--service-persons",
                "60",
                "--minutes",
                "1",
                "--tick-seconds",
                "1",
                "--drain-seconds",
                "240",
                "--walk-units-per-tick",
                "3.5",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            facility_kind="elevator",
            demand_hour=600,
            service_persons_per_min=60,
            seed=1,
        )

        result = probe.run_case_with_animation(args, case)
        row = result.row

        self.assertEqual("ok", row["status"])
        self.assertEqual("cleared", row["clearance"])
        self.assertGreaterEqual(row["departed_cabins"], 2)
        self.assertLessEqual(row["service_persons_max"], 8)
        self.assertLessEqual(row["last_departure_load_persons"], 8)

        assert result.animation is not None
        first_departure = next(
            frame
            for frame in result.animation["frames"]
            if frame["facility"].get("departed_cabins") == 1
        )
        self.assertEqual(8, first_departure["facility"]["cabin_load"])

    def test_elevator_queueing_does_not_snap_to_tail(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--kinds",
                "elevator",
                "--demands",
                "960",
                "--service-persons",
                "60",
                "--minutes",
                "2",
                "--tick-seconds",
                "1",
                "--drain-seconds",
                "360",
                "--walk-units-per-tick",
                "0.9",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            facility_kind="elevator",
            demand_hour=960,
            service_persons_per_min=60,
            seed=1,
        )

        result = probe.run_case_with_animation(args, case)

        assert result.animation is not None
        max_join_jump = 0.0
        join_transitions = 0
        for previous, current in zip(
            result.animation["frames"],
            result.animation["frames"][1:],
        ):
            previous_by_id = {
                passenger["id"]: passenger for passenger in previous["passengers"]
            }
            for passenger in current["passengers"]:
                if passenger["state"] != "queueing_vertical":
                    continue
                previous_passenger = previous_by_id.get(passenger["id"])
                if (
                    previous_passenger is None
                    or previous_passenger["state"] == "queueing_vertical"
                ):
                    continue
                join_transitions += 1
                max_join_jump = max(
                    max_join_jump,
                    hypot(
                        passenger["x"] - previous_passenger["x"],
                        passenger["y"] - previous_passenger["y"],
                    ),
                )

        self.assertGreater(join_transitions, 0)
        self.assertLessEqual(max_join_jump, 2.1)

    def test_write_outputs_creates_csv_json_markdown_and_html(self) -> None:
        args = probe.build_parser().parse_args(
            ["--kinds", "stairs", "--demands", "120", "--service-persons", "55"]
        )
        case = probe.ProbeCase(
            facility_kind="stairs",
            demand_hour=120,
            service_persons_per_min=55,
            seed=42,
        )
        row = {field: None for field in probe.FIELDNAMES}
        row.update(
            {
                "run_id": case.run_id,
                "status": "ok",
                "clearance": "cleared",
                "facility_kind": "stairs",
                "demand_hour": 120,
                "service_persons_per_min": 55,
                "source_persons": 2,
                "served_persons": 2,
                "sink_persons": 2,
                "unserved_persons": 0,
                "queue_persons_max": 1,
                "service_persons_max": 2,
            }
        )
        animation = {
            "run_id": case.run_id,
            "label": "unit animation",
            "scenario": {
                "world_width": 36.0,
                "world_height": 12.0,
                "facility_kind": "stairs",
                "source_position": [2.0, 6.0],
                "facility_position": [25.4, 6.0],
                "pre_capture_targets": [[22.5, 6.0]],
                "queue_slots": [[24.0, 6.0]],
                "exit_position": [31.2, 6.0],
            },
            "summary": {"source_persons": 2, "unserved_persons": 0},
            "frames": [
                {
                    "time_seconds": 0,
                    "passengers": [
                        {"id": 1, "x": 2.0, "y": 6.0, "state": "walking_to_vertical"}
                    ],
                    "approach_persons": 1,
                    "queue_persons": 0,
                    "service_persons": 0,
                    "sink_persons": 0,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = probe.OutputPaths(
                csv_path=probe.Path(tmp_dir) / "vertical.csv",
                json_path=probe.Path(tmp_dir) / "vertical.json",
                markdown_path=probe.Path(tmp_dir) / "vertical.md",
                animation_html_path=probe.Path(tmp_dir) / "vertical_animation.html",
            )

            probe.write_outputs(
                paths,
                args=args,
                cases=[case],
                rows=[row],
                animations=[animation],
            )

            self.assertIn("facility_kind", paths.csv_path.read_text(encoding="utf-8"))
            json_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, json_payload["summary"]["ok"])
            markdown_text = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Vertical Flow Probe Summary", markdown_text)
            html_text = paths.animation_html_path.read_text(encoding="utf-8")
            self.assertIn("VERTICAL_FLOW_ANIMATION_DATA", html_text)
            self.assertIn("function displayPassengers", html_text)
            self.assertIn("<canvas", html_text)


if __name__ == "__main__":
    unittest.main()
