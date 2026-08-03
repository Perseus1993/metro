from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sandbox.metro_station_sandbox.facilities.process import FacilityKind
from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from sandbox.metro_station_sandbox.planning.plan import AgentState
from metro_station_testkit.goal_boarding_probe import (
    GOAL_BOARDING_COMPONENT_PROBE,
    GoalBoardingPhysicalProbe,
)
from scripts.run_goal_boarding_probe import build_report, main, render_markdown


JPS_AVAILABLE = JuPedSimAdapter().status.available


@unittest.skipUnless(JPS_AVAILABLE, "JuPedSim is unavailable")
class GoalBoardingProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(seed=42)
        cls.scenarios = {
            scenario["scenario_id"]: scenario for scenario in cls.report["scenarios"]
        }

    def test_all_scenarios_use_real_joint_components(self) -> None:
        summary = self.report["summary"]
        self.assertEqual("ok", summary["status"])
        self.assertEqual(6, summary["passed_scenarios"])
        self.assertGreater(summary["jupedsim_steps"], 0)
        self.assertEqual(
            (
                "goal_graph",
                "boarding_door_process",
                "train_dwell_capacity",
                "jupedsim_movement",
            ),
            GOAL_BOARDING_COMPONENT_PROBE.component_ids,
        )

    def test_natural_passenger_queues_before_train_and_then_boards(self) -> None:
        scenario = self.scenarios["natural_boarding"]
        joined = next(trace for trace in scenario["traces"] if trace["event_kind"] == "queue_joined")
        started = next(
            trace for trace in scenario["traces"] if trace["event_kind"] == "service_started"
        )
        self.assertEqual("away", joined["train_state"])
        self.assertEqual("boarding", started["train_state"])
        self.assertLess(joined["time_seconds"], started["time_seconds"])
        self.assertEqual("complete", scenario["final_state"]["current_node_id"])

    def test_boarding_service_emits_train_door_event(self) -> None:
        probe = GoalBoardingPhysicalProbe("natural_boarding", seed=42)
        result = probe.run()
        event = probe.scene.facility_service_events[0]

        self.assertEqual(FacilityKind.TRAIN_DOOR.value, event.facility_kind)
        self.assertEqual((probe.scene.subject.unique_id,), event.passenger_ids)
        self.assertEqual(event.end_position, probe.scene.subject.pos)
        self.assertEqual(1, result.movement["boarding_service_events"])
        self.assertEqual(1, probe.scene.train.current_load_persons)

    def test_door_crowd_reroutes_to_second_door(self) -> None:
        scenario = self.scenarios["door_front_crowded"]
        facilities = [trace["committed_facility_id"] for trace in scenario["traces"]]
        self.assertIn("door_1", facilities)
        self.assertIn("door_2", facilities)
        self.assertTrue(any(trace["blocker_count"] > 0 for trace in scenario["traces"]))

    def test_alighting_conflict_must_clear_before_boarding(self) -> None:
        scenario = self.scenarios["alighting_conflict"]
        stalls = [trace for trace in scenario["traces"] if trace["event_kind"] == "progress_stalled"]
        completed = next(
            trace for trace in scenario["traces"] if trace["event_kind"] == "service_completed"
        )
        self.assertTrue(stalls)
        self.assertTrue(all(trace["train_state"] == "boarding" for trace in stalls))
        self.assertGreater(completed["time_seconds"], stalls[0]["time_seconds"])
        self.assertEqual(1, scenario["movement"]["boarded_persons"])

    def test_full_train_and_closed_train_never_false_board(self) -> None:
        full = self.scenarios["train_full"]
        closed = self.scenarios["train_not_open"]
        for scenario in (full, closed):
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertNotEqual("complete", scenario["final_state"]["current_node_id"])
                self.assertEqual(0, scenario["movement"]["boarded_persons"])
                self.assertEqual(0, scenario["movement"]["boarding_service_events"])

    def test_completed_passenger_never_returns_to_platform(self) -> None:
        scenario = self.scenarios["no_platform_return"]
        self.assertEqual(AgentState.DEPARTED.value, scenario["final_passenger_state"])
        self.assertTrue(scenario["checks"]["not_readded_to_platform"])
        self.assertTrue(scenario["checks"]["not_requeued"])
        self.assertTrue(scenario["checks"]["post_completion_observed"])

    def test_markdown_and_cli_write_train_capacity_trace(self) -> None:
        markdown = render_markdown(self.report)
        self.assertIn("载客/余量", markdown)
        self.assertIn("上车服务事件", markdown)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "boarding.json"
            markdown_out = root / "boarding.md"
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
            self.assertIn("列车", markdown_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
