from __future__ import annotations

import json
import tempfile
import unittest

from scripts import run_turnstile_flow_probe as probe


class TurnstileFlowProbeTests(unittest.TestCase):
    def test_parse_int_list_and_arrival_schedule_profiles(self) -> None:
        self.assertEqual((120, 600, 1200), probe.parse_int_list("120,600,1200"))

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
        self.assertLessEqual(max(uniform), 11)

    def test_run_case_clears_source_gate_sink_flow(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "120",
                "--gate-services",
                "60",
                "--minutes",
                "1",
                "--drain-seconds",
                "60",
                "--walk-units-per-tick",
                "3.5",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=120,
            gate_service_persons_per_min=60,
            seed=1,
        )

        row = probe.run_case(args, case)

        self.assertEqual("ok", row["status"])
        self.assertEqual("cleared", row["clearance"])
        self.assertEqual(2, row["source_persons"])
        self.assertEqual(row["source_persons"], row["served_persons"])
        self.assertEqual(row["source_persons"], row["sink_persons"])
        self.assertEqual(0, row["unserved_persons"])
        self.assertGreater(row["approach_persons_max"], 0)

        model = probe.make_model(args, case)
        passenger = model.spawn_source_passenger(local_index=0)
        passenger.pos = model.gate.spec.queue_layout.slot(0)
        model.gate.join_queue(passenger, authority="goal_graph")
        for _ in range(3):
            model.run_step(arrivals=0)
        self.assertEqual(1, len(model.facility_completion_observations))

    def test_run_case_reports_backlog_for_overloaded_turnstile(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "1200",
                "--gate-services",
                "6",
                "--minutes",
                "1",
                "--drain-seconds",
                "0",
                "--walk-units-per-tick",
                "3.5",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=1200,
            gate_service_persons_per_min=6,
            seed=1,
        )

        row = probe.run_case(args, case)

        self.assertEqual("ok", row["status"])
        self.assertEqual("backlog", row["clearance"])
        self.assertGreater(row["source_persons"], row["sink_persons"])
        self.assertGreater(row["unserved_persons"], 0)
        self.assertGreater(row["queue_persons_max"] + row["approach_persons_max"], 0)

    def test_empty_gate_does_not_accumulate_preloaded_service_credit(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "60",
                "--gate-services",
                "6",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=60,
            gate_service_persons_per_min=6,
            seed=1,
        )
        model = probe.make_model(args, case)

        for step in range(3):
            model.step_index = step
            model.gate.step()

        self.assertEqual(0.0, model.gate.service_credit)

        passenger = model.spawn_source_passenger(local_index=0)
        passenger.pos = model.gate.spec.queue_layout.slot(0)
        model.gate.join_queue(passenger, authority="goal_graph")
        model.step_index = 3
        model.gate.step()

        self.assertEqual(0, model.gate.served_persons)
        self.assertIn(passenger, model.gate.queue)

    def test_gate_queue_layout_rejects_shared_anchor_arrivals(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "60",
                "--gate-services",
                "1",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=60,
            gate_service_persons_per_min=1,
            seed=1,
        )
        model = probe.make_model(args, case)
        anchor = model.gate.spec.queue_layout.slot(0)
        for local_index in range(8):
            passenger = model.spawn_source_passenger(local_index=local_index)
            passenger.pos = anchor
            model.gate.join_queue(passenger, authority="goal_graph")

        # Admission/routing owns overlap prevention.  Once an invalid
        # co-located queue has already been recorded, layout must fail closed
        # instead of fabricating a collision-free fan-out.
        with self.assertRaisesRegex(RuntimeError, "co-located bodies"):
            model.gate.step()

    def test_approach_targets_fan_into_pre_gate_zone(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "300",
                "--gate-services",
                "30",
                "--movement-backend",
                "linear",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=300,
            gate_service_persons_per_min=30,
            seed=1,
        )
        model = probe.make_model(args, case)
        passengers = [
            model.spawn_source_passenger(local_index=local_index)
            for local_index in range(5)
        ]

        model._target_approaching_passengers()

        target_positions = {
            (round(passenger.target[0], 2), round(passenger.target[1], 2))
            for passenger in passengers
        }
        self.assertGreater(
            len(target_positions),
            1,
        )

    def test_stochastic_gate_holds_service_before_releasing_to_sink(self) -> None:
        args = probe.build_parser().parse_args(
            [
                "--demands",
                "60",
                "--gate-services",
                "60",
                "--tick-seconds",
                "1",
                "--movement-backend",
                "linear",
                "--gate-service-mode",
                "stochastic",
                "--tap-jitter-seconds",
                "0",
                "--tap-failure-probability",
                "0",
            ]
        )
        case = probe.ProbeCase(
            demand_hour=60,
            gate_service_persons_per_min=60,
            seed=1,
        )
        model = probe.make_model(args, case)
        passenger = model.spawn_source_passenger(local_index=0)
        passenger.pos = model.gate.spec.queue_layout.slot(0)
        model.gate.join_queue(passenger, authority="goal_graph")

        model.step_index = 0
        model.gate.step()

        self.assertEqual(probe.AgentState.PASSING_GATE.value, passenger.state)
        self.assertEqual(model.gate.spec.position, passenger.pos)
        self.assertEqual(1, model.gate.active_service_persons)
        self.assertEqual(0, model.sink_persons)

        model.step_index = 1
        model.gate.step()

        self.assertEqual(probe.AgentState.DEPARTED.value, passenger.state)
        self.assertEqual(1, model.sink_persons)
        self.assertEqual(1, model.gate.served_persons)
        self.assertEqual(1, len(model.facility_service_events))
        self.assertEqual(
            model.gate.spec.position,
            model.facility_service_events[0].start_position,
        )
        self.assertEqual(
            passenger.pos,
            model.facility_service_events[0].end_position,
        )

    def test_write_outputs_creates_csv_json_and_markdown(self) -> None:
        args = probe.build_parser().parse_args(["--demands", "120", "--gate-services", "55"])
        case = probe.ProbeCase(
            demand_hour=120,
            gate_service_persons_per_min=55,
            seed=42,
        )
        row = {field: None for field in probe.FIELDNAMES}
        row.update(
            {
                "run_id": case.run_id,
                "status": "ok",
                "clearance": "cleared",
                "demand_hour": 120,
                "gate_service_persons_per_min": 55,
                "source_persons": 2,
                "served_persons": 2,
                "sink_persons": 2,
                "unserved_persons": 0,
                "queue_persons_max": 1,
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = probe.OutputPaths(
                csv_path=probe.Path(tmp_dir) / "turnstile.csv",
                json_path=probe.Path(tmp_dir) / "turnstile.json",
                markdown_path=probe.Path(tmp_dir) / "turnstile.md",
                animation_html_path=probe.Path(tmp_dir) / "turnstile_animation.html",
            )

            animation = {
                "run_id": case.run_id,
                "label": "unit animation",
                "scenario": {
                    "world_width": 14.0,
                    "world_height": 8.0,
                    "source_position": [1.0, 4.0],
                    "gate_position": [9.0, 4.0],
                    "queue_anchor": [8.0, 4.0],
                    "queue_row_step": [-0.7, 0.0],
                    "exit_position": [10.4, 4.0],
                },
                "summary": {"source_persons": 2, "unserved_persons": 0},
                "frames": [
                    {
                        "time_seconds": 0,
                        "passengers": [{"id": 1, "x": 1.0, "y": 4.0, "state": "entering_station"}],
                        "approach_persons": 1,
                        "queue_persons": 0,
                        "sink_persons": 0,
                    }
                ],
            }

            probe.write_outputs(paths, args=args, cases=[case], rows=[row], animations=[animation])

            self.assertIn(
                "gate_service_persons_per_min",
                paths.csv_path.read_text(encoding="utf-8"),
            )
            json_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, json_payload["summary"]["ok"])
            markdown_text = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Turnstile Flow Probe Summary", markdown_text)
            html_text = paths.animation_html_path.read_text(encoding="utf-8")
            self.assertIn("TURNSTILE_ANIMATION_DATA", html_text)
            self.assertIn("<canvas", html_text)


if __name__ == "__main__":
    unittest.main()
