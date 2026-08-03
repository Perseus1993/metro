from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from sandbox.metro_station_sandbox.planning.plan import AgentState
from metro_station_testkit.goal_journey_fixture import (
    CONCOURSE_LEVEL,
    PLATFORM_LEVEL,
)
from metro_station_testkit.goal_journey_probe import (
    GOAL_JOURNEY_COMPONENT_PROBE,
    GoalJourneyPhysicalProbe,
)
from scripts.run_goal_journey_probe import build_report, main, render_markdown


JPS_AVAILABLE = JuPedSimAdapter().status.available


@unittest.skipUnless(JPS_AVAILABLE, "JuPedSim is unavailable")
class GoalJourneyProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(seed=42)
        cls.scenarios = {
            scenario["scenario_id"]: scenario for scenario in cls.report["scenarios"]
        }

    def test_all_scenarios_use_full_joint_component_boundary(self) -> None:
        summary = self.report["summary"]
        self.assertEqual("ok", summary["status"])
        self.assertEqual(8, summary["passed_scenarios"])
        self.assertGreater(summary["jupedsim_steps"], 0)
        self.assertEqual(7, len(GOAL_JOURNEY_COMPONENT_PROBE.component_ids))

    def test_natural_journey_services_gate_stairs_and_train_door_in_order(self) -> None:
        scenario = self.scenarios["natural_full_journey"]
        self.assertEqual(["gate", "stairs", "train_door"], scenario["movement"]["service_kinds"])
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])
        self.assertEqual(AgentState.DEPARTED.value, scenario["final_passenger_state"])
        self.assertEqual(PLATFORM_LEVEL, scenario["final_level_id"])

    def test_same_passenger_owns_all_three_service_events(self) -> None:
        probe = GoalJourneyPhysicalProbe("natural_full_journey", seed=42)
        probe.run()
        passenger_ids = {
            passenger_id
            for event in probe.scene.facility_service_events
            for passenger_id in event.passenger_ids
        }
        self.assertEqual({probe.scene.subject.unique_id}, passenger_ids)
        self.assertEqual(3, len(probe.scene.facility_service_events))

    def test_crowded_journey_replans_all_three_facility_stages(self) -> None:
        scenario = self.scenarios["crowded_full_journey"]
        stalls = [
            trace for trace in scenario["traces"] if trace["event_kind"] == "progress_stalled"
        ]
        self.assertGreaterEqual(len(stalls), 3)
        self.assertEqual(
            {"entry_gate", "vertical_transfer", "boarding_door"},
            {trace["current_stage"] for trace in stalls},
        )
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_each_facility_stage_can_replan_independently(self) -> None:
        cases = (
            ("gate_replan", "gate_1", "gate_2"),
            ("stairs_replan", "stairs_1", "stairs_2"),
            ("door_replan", "door_1", "door_2"),
        )
        for scenario_id, first, second in cases:
            with self.subTest(scenario=scenario_id):
                scenario = self.scenarios[scenario_id]
                facilities = [trace["committed_facility_id"] for trace in scenario["traces"]]
                self.assertIn(first, facilities)
                self.assertIn(second, facilities)
                self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_delayed_train_keeps_passenger_in_final_queue(self) -> None:
        scenario = self.scenarios["delayed_train"]
        joined = [
            trace["time_seconds"]
            for trace in scenario["traces"]
            if trace["event_kind"] == "queue_joined"
        ][-1]
        started = [
            trace["time_seconds"]
            for trace in scenario["traces"]
            if trace["event_kind"] == "service_started"
        ][-1]
        self.assertGreaterEqual(started - joined, 9.5)
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_full_train_blocks_only_the_final_stage(self) -> None:
        scenario = self.scenarios["train_full_after_full_journey"]
        self.assertEqual(["gate", "stairs"], scenario["movement"]["service_kinds"])
        self.assertEqual("use_boarding_door", scenario["final_state"]["current_node_id"])
        self.assertEqual(PLATFORM_LEVEL, scenario["final_level_id"])
        self.assertEqual(0, scenario["movement"]["boarded_persons"])

    def test_vertical_level_changes_only_after_stairs_complete(self) -> None:
        scenario = self.scenarios["natural_full_journey"]
        stairs_started = next(
            trace
            for trace in scenario["traces"]
            if trace["event_kind"] == "service_started"
            and trace["before_graph_state"].startswith("use_vertical_transfer")
        )
        stairs_completed = next(
            trace
            for trace in scenario["traces"]
            if trace["event_kind"] == "service_completed"
            and trace["before_graph_state"].startswith("use_vertical_transfer")
        )
        self.assertEqual(CONCOURSE_LEVEL, stairs_started["level_id"])
        self.assertEqual(PLATFORM_LEVEL, stairs_completed["level_id"])

    def test_completed_journey_never_reenters_station_components(self) -> None:
        scenario = self.scenarios["no_stage_regression"]
        self.assertTrue(scenario["checks"]["post_completion_observed"])
        self.assertTrue(scenario["checks"]["no_level_regression"])
        self.assertTrue(scenario["checks"]["not_readded"])
        self.assertTrue(scenario["checks"]["not_requeued"])

    def test_markdown_and_cli_write_end_to_end_trace(self) -> None:
        markdown = render_markdown(self.report)
        self.assertIn("gate → stairs → train_door", markdown)
        self.assertIn("最终楼层", markdown)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "journey.json"
            markdown_out = root / "journey.md"
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
            payload = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual("ok", payload["summary"]["status"])
            self.assertIn("服务顺序", markdown_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
