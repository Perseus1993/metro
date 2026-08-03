from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_goal_graph_probe import build_report, main, render_markdown


class GoalGraphProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = build_report()
        self.scenarios = {
            scenario["scenario_id"]: scenario for scenario in self.report["scenarios"]
        }

    def test_all_four_scenarios_pass_without_physics_frameworks(self) -> None:
        summary = self.report["summary"]
        self.assertEqual("ok", summary["status"])
        self.assertEqual(4, summary["scenario_count"])
        self.assertEqual(4, summary["passed_scenarios"])
        self.assertFalse(summary["uses_mesa"])
        self.assertFalse(summary["uses_jupedsim"])

    def test_natural_flow_reaches_complete(self) -> None:
        scenario = self.scenarios["natural_flow"]
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])
        self.assertTrue(scenario["checks"]["journey_completed"])

    def test_people_blockage_causes_physical_stall_then_reroute(self) -> None:
        scenario = self.scenarios["gate_blocked_by_people"]
        commitments = [step["after_facility"] for step in scenario["steps"]]
        self.assertIn("gate_1", commitments)
        self.assertIn("gate_2", commitments)
        stalled = next(
            step
            for step in scenario["steps"]
            if step["event_kind"] == "progress_stalled"
        )
        self.assertEqual("replan_pending", stalled["after_interaction"])

    def test_paid_hall_crowding_never_rolls_graph_back_to_gate(self) -> None:
        scenario = self.scenarios["paid_hall_crowded"]
        stalled = [
            step
            for step in scenario["steps"]
            if step["event_kind"] == "progress_stalled"
        ]
        self.assertEqual(2, len(stalled))
        self.assertTrue(all(step["after_node"] == "enter_paid_hall" for step in stalled))
        self.assertTrue(all(not step["handled"] for step in stalled))

    def test_unavailable_gate_never_produces_false_completion(self) -> None:
        scenario = self.scenarios["gate_unavailable"]
        final_state = scenario["final_state"]
        self.assertEqual("use_entry_gate", final_state["current_node_id"])
        self.assertEqual("evaluate_candidates", final_state["interaction_state"])
        self.assertIsNone(final_state["commitment"])

    def test_markdown_contains_state_transition_tables(self) -> None:
        markdown = render_markdown(self.report)
        for label in ("自然状态", "闸机被其他人堵住", "闸机后大量人员拥堵", "闸机无法通过"):
            self.assertIn(label, markdown)
        self.assertIn("| 步骤 | 时间 | 输入事件 |", markdown)

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "probe.json"
            markdown_out = root / "probe.md"
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
            self.assertIn("Goal Graph", markdown_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
