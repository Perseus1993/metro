from __future__ import annotations

import json
import subprocess
import sys
import unittest
from importlib import import_module


class OfficialPackageTests(unittest.TestCase):
    def test_package_has_official_version(self) -> None:
        import metro_station

        self.assertEqual(metro_station.__version__, "0.1.0")

    def test_legacy_goal_imports_preserve_type_identity(self) -> None:
        from metro_station.domain.goals import GoalEvent as OfficialGoalEvent
        from metro_station.domain.goals import (
            EventDrivenGoalStateMachine as OfficialStateMachine,
        )
        from metro_station.domain.goals import JourneyGraph as OfficialJourneyGraph
        from metro_station.domain.passengers import AgentIntent as OfficialAgentIntent
        EventDrivenGoalStateMachine = getattr(
            import_module("sandbox.metro_station_sandbox.planning.default_goal_state_machine"),
            "EventDrivenGoalStateMachine",
        )
        GoalEvent = getattr(
            import_module("sandbox.metro_station_sandbox.planning.goal_events"),
            "GoalEvent",
        )
        JourneyGraph = getattr(
            import_module("sandbox.metro_station_sandbox.planning.goal_graph"),
            "JourneyGraph",
        )
        AgentIntent = getattr(
            import_module("sandbox.metro_station_sandbox.planning.plan"),
            "AgentIntent",
        )

        self.assertIs(GoalEvent, OfficialGoalEvent)
        self.assertIs(EventDrivenGoalStateMachine, OfficialStateMachine)
        self.assertIs(JourneyGraph, OfficialJourneyGraph)
        self.assertIs(AgentIntent, OfficialAgentIntent)

    def test_validate_design_command_uses_existing_authority(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "metro_station",
                "validate-design",
                "--design-template",
                "two_level_island_platform",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["design_template"], "two_level_island_platform")


if __name__ == "__main__":
    unittest.main()
