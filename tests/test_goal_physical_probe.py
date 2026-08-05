from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from metro_station_testkit.goal_gate_physical_probe import GoalGatePhysicalProbe
from scripts.run_goal_physical_probe import build_report, main, render_markdown


JPS_AVAILABLE = JuPedSimAdapter().status.available


@unittest.skipUnless(JPS_AVAILABLE, "JuPedSim is unavailable")
class GoalPhysicalProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(seed=42)
        cls.scenarios = {
            scenario["scenario_id"]: scenario for scenario in cls.report["scenarios"]
        }

    def test_all_scenarios_pass_with_real_jupedsim_steps(self) -> None:
        summary = self.report["summary"]
        self.assertEqual("ok", summary["status"])
        self.assertEqual(4, summary["passed_scenarios"])
        self.assertGreater(summary["jupedsim_steps"], 0)
        for scenario in self.report["scenarios"]:
            self.assertEqual("BatchedJuPedSimMovementBackend", scenario["movement"]["backend"])
            self.assertTrue(scenario["movement"]["physical_clock"]["research_valid"])

    def test_natural_flow_physically_reaches_paid_hall(self) -> None:
        scenario = self.scenarios["natural_flow"]
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])
        self.assertGreater(scenario["final_position"][0], 24.0)

    def test_gate_event_uses_exact_native_trace_boundaries(self) -> None:
        probe = GoalGatePhysicalProbe("natural_flow", seed=42)
        probe.run()
        event = probe.scene.facility_service_events[0]
        points = [
            point
            for point in probe.scene.movement_backend.movement_trace()["points"]
            if point["passenger_id"] == probe.scene.subject.unique_id
            and point["phase"] == "same_floor_facility"
        ]

        self.assertTrue(points)
        self.assertAlmostEqual(event.start_time, points[0]["time_seconds"], places=6)
        self.assertAlmostEqual(event.end_time, points[-1]["time_seconds"], places=6)
        self.assertTrue(
            all(
                right["time_seconds"] - left["time_seconds"] <= 0.200001
                for left, right in zip(points, points[1:])
            )
        )

    def test_people_blockage_is_observed_and_rerouted(self) -> None:
        scenario = self.scenarios["gate_blocked_by_people"]
        facilities = [trace["committed_facility_id"] for trace in scenario["traces"]]
        self.assertIn("gate_1", facilities)
        self.assertIn("gate_2", facilities)
        self.assertTrue(any(trace["blocker_count"] > 0 for trace in scenario["traces"]))
        self.assertTrue(any(trace["event_kind"] == "progress_stalled" for trace in scenario["traces"]))

    def test_paid_hall_crowd_stalls_without_graph_regression(self) -> None:
        scenario = self.scenarios["paid_hall_crowded"]
        stalls = [trace for trace in scenario["traces"] if trace["event_kind"] == "progress_stalled"]
        self.assertTrue(stalls)
        self.assertTrue(all(trace["after_graph_state"] == "enter_paid_hall" for trace in stalls))
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_disabled_gates_never_false_complete(self) -> None:
        scenario = self.scenarios["gate_unavailable"]
        self.assertEqual("use_entry_gate", scenario["final_state"]["current_node_id"])
        self.assertEqual("waiting_capacity", scenario["final_state"]["interaction_state"])
        self.assertIsNone(scenario["final_state"]["commitment"])

    def test_markdown_reports_physical_and_graph_state_together(self) -> None:
        markdown = render_markdown(self.report)
        self.assertIn("物理位置", markdown)
        self.assertIn("Graph之前", markdown)
        self.assertIn("JuPedSim乘客步", markdown)

    def test_cli_writes_report_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "physical.json"
            markdown_out = root / "physical.md"
            status = main(
                [
                    "--json-out",
                    str(json_out),
                    "--markdown-out",
                    str(markdown_out),
                    "--quiet",
                ]
            )
            self.assertEqual(0, status)
            self.assertEqual("ok", json.loads(json_out.read_text(encoding="utf-8"))["summary"]["status"])
            self.assertIn("JuPedSim", markdown_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
