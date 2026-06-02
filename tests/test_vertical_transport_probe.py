from __future__ import annotations

import json
import tempfile
import unittest

from scripts import run_vertical_transport_probe as probe


class VerticalTransportProbeTests(unittest.TestCase):
    def test_parse_int_list_and_arrival_schedule(self) -> None:
        self.assertEqual((60, 240, 1000), probe.parse_int_list("60,240,1000"))

        schedule = probe.arrival_schedule(
            demand_hour=120,
            minutes=10,
            tick_seconds=5,
            group_size=1,
        )

        self.assertEqual(20, sum(schedule.values()))
        self.assertIn(0, schedule)
        self.assertLessEqual(max(schedule), 119)

    def test_selected_facilities_filters_kind_direction_and_exact_id(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "60",
                "--kinds",
                "elevator",
                "--directions",
                "down",
            ]
        )
        model = probe.make_model(args, seed=1)

        elevators = probe.selected_facilities(
            model.vertical_transports,
            kinds=("elevator",),
            directions=("down",),
            facility_id=None,
        )

        self.assertTrue(elevators)
        self.assertTrue(all(item.spec.kind == "elevator" for item in elevators))
        self.assertTrue(all(item.spec.direction == "down" for item in elevators))

        exact = probe.selected_facilities(
            model.vertical_transports,
            kinds=("escalator",),
            directions=("up",),
            facility_id=elevators[0].facility_id,
        )

        self.assertEqual([elevators[0].facility_id], [item.facility_id for item in exact])

    def test_run_case_reports_backlog_for_overloaded_elevator(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "1000",
                "--minutes",
                "2",
                "--drain-seconds",
                "0",
                "--kinds",
                "elevator",
                "--directions",
                "down",
            ]
        )
        model = probe.make_model(args, seed=1)
        facility = probe.selected_facilities(
            model.vertical_transports,
            kinds=("elevator",),
            directions=("down",),
            facility_id=None,
        )[0]
        case = probe.ProbeCase(facility_id=facility.facility_id, demand_hour=1000, seed=1)

        row = probe.run_case(args, case)

        self.assertEqual("ok", row["status"])
        self.assertEqual("backlog", row["clearance"])
        self.assertGreater(row["arrived_persons"], row["served_persons"])
        self.assertGreater(row["departed_cabins"], 0)

    def test_write_outputs_creates_csv_json_and_markdown(self) -> None:
        args = probe.build_parser().parse_args(["--demands", "60"])
        case = probe.ProbeCase("vertical:test:down:a:b", demand_hour=60, seed=42)
        row = {field: None for field in probe.FIELDNAMES}
        row.update(
            {
                "run_id": case.run_id,
                "status": "ok",
                "clearance": "cleared",
                "facility_id": case.facility_id,
                "facility_kind": "escalator",
                "direction": "down",
                "demand_hour": 60,
                "arrived_persons": 10,
                "served_persons": 10,
                "unserved_persons": 0,
                "queue_persons_max": 1,
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = probe.OutputPaths(
                csv_path=probe.Path(tmp_dir) / "probe.csv",
                json_path=probe.Path(tmp_dir) / "probe.json",
                markdown_path=probe.Path(tmp_dir) / "probe.md",
            )

            probe.write_outputs(paths, args=args, cases=[case], rows=[row])

            self.assertIn("facility_kind", paths.csv_path.read_text(encoding="utf-8"))
            json_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, json_payload["summary"]["ok"])
            markdown_text = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Vertical Transport Probe Summary", markdown_text)


if __name__ == "__main__":
    unittest.main()
