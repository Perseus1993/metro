from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from metro_station_testkit.goal_stairs_fixture import (
    CONCOURSE_LEVEL,
    PLATFORM_LEVEL,
)
from metro_station_testkit.goal_stairs_probe import (
    GOAL_STAIRS_COMPONENT_PROBE,
    GoalStairsPhysicalProbe,
)
from scripts.run_goal_stairs_probe import build_report, main, render_markdown


JPS_AVAILABLE = JuPedSimAdapter().status.available


@unittest.skipUnless(JPS_AVAILABLE, "JuPedSim is unavailable")
class GoalStairsProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(seed=42)
        cls.scenarios = {
            scenario["scenario_id"]: scenario for scenario in cls.report["scenarios"]
        }

    def test_all_scenarios_use_real_joint_components(self) -> None:
        summary = self.report["summary"]
        self.assertEqual("ok", summary["status"])
        self.assertEqual(5, summary["passed_scenarios"])
        self.assertGreater(summary["jupedsim_steps"], 0)
        self.assertEqual(
            ("goal_graph", "stairs_process", "level_transition", "jupedsim_movement"),
            GOAL_STAIRS_COMPONENT_PROBE.component_ids,
        )

    def test_natural_descent_completes_one_vertical_service(self) -> None:
        scenario = self.scenarios["natural_descent"]
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])
        self.assertEqual(PLATFORM_LEVEL, scenario["final_level_id"])
        self.assertEqual(1, scenario["movement"]["vertical_service_events"])

    def test_service_completion_waits_for_physical_stair_ride(self) -> None:
        probe = GoalStairsPhysicalProbe("natural_descent", seed=42)
        result = probe.run()
        event = probe.scene.facility_service_events[0]
        started = next(trace for trace in result.traces if trace.event_kind == "service_started")
        completed = next(
            trace for trace in result.traces if trace.event_kind == "service_completed"
        )

        self.assertLess(started.time_seconds, completed.time_seconds)
        self.assertGreaterEqual(completed.time_seconds, event.end_time)
        self.assertEqual(CONCOURSE_LEVEL, started.current_level_id)
        self.assertEqual(PLATFORM_LEVEL, completed.current_level_id)
        self.assertLess(started.position[0], completed.position[0])

    def test_entrance_crowd_reroutes_to_second_stairs(self) -> None:
        scenario = self.scenarios["entrance_crowded"]
        facilities = [trace["committed_facility_id"] for trace in scenario["traces"]]
        self.assertIn("stairs_1", facilities)
        self.assertIn("stairs_2", facilities)
        self.assertTrue(any(trace["blocker_count"] > 0 for trace in scenario["traces"]))

    def test_exit_crowd_does_not_regress_graph(self) -> None:
        scenario = self.scenarios["exit_crowded"]
        stalls = [trace for trace in scenario["traces"] if trace["event_kind"] == "progress_stalled"]
        self.assertTrue(stalls)
        self.assertTrue(
            all(trace["after_graph_state"] == "enter_platform_landing" for trace in stalls)
        )
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_unavailable_stairs_never_change_level_or_false_complete(self) -> None:
        scenario = self.scenarios["stairs_unavailable"]
        self.assertEqual("use_vertical_transfer", scenario["final_state"]["current_node_id"])
        self.assertEqual(CONCOURSE_LEVEL, scenario["final_level_id"])
        self.assertEqual(0, scenario["movement"]["vertical_service_events"])
        self.assertIsNone(scenario["final_state"]["commitment"])

    def test_completed_passenger_never_returns_to_concourse(self) -> None:
        scenario = self.scenarios["no_level_regression"]
        levels = [trace["current_level_id"] for trace in scenario["traces"]]
        platform_index = levels.index(PLATFORM_LEVEL)
        self.assertNotIn(CONCOURSE_LEVEL, levels[platform_index:])
        self.assertTrue(scenario["checks"]["post_completion_observed"])
        self.assertTrue(scenario["checks"]["no_second_vertical_service"])
        self.assertTrue(scenario["checks"]["never_reentered_stairs"])

    def test_markdown_and_cli_write_physical_level_trace(self) -> None:
        markdown = render_markdown(self.report)
        self.assertIn("最终楼层", markdown)
        self.assertIn("垂直服务事件", markdown)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "stairs.json"
            markdown_out = root / "stairs.md"
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
            self.assertIn("楼层", markdown_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
