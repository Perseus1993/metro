from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from sandbox.metro_station_sandbox.runtime.goal_authority_audit import (
    audit_goal_authority,
)
from metro_station_testkit.goal_boarding_adapter import (
    GoalBoardingObservationAdapter,
)
from metro_station_testkit.goal_boarding_command_executor import (
    GoalBoardingCommandExecutor,
)
from metro_station_testkit.goal_boarding_service_observer import (
    GoalBoardingServiceObserver,
)
from metro_station_testkit.goal_gate_adapter import (
    GoalGateObservationAdapter,
)
from metro_station_testkit.goal_gate_command_executor import (
    GoalGateCommandExecutor,
)
from metro_station_testkit.goal_gate_service_observer import (
    GoalGateServiceObserver,
)
from metro_station_testkit.goal_journey_adapter import (
    GoalJourneyObservationAdapter,
)
from metro_station_testkit.goal_journey_command_executor import (
    GoalJourneyCommandExecutor,
)
from metro_station_testkit.goal_journey_service_observer import (
    GoalJourneyServiceObserver,
)
from sandbox.metro_station_sandbox.runtime.goal_ports import (
    CommandExecutor,
    RuntimeObservationAdapter,
    ServiceEventObserver,
)
from metro_station_testkit.goal_stairs_adapter import (
    GoalStairsObservationAdapter,
)
from metro_station_testkit.goal_stairs_command_executor import (
    GoalStairsCommandExecutor,
)
from metro_station_testkit.goal_stairs_service_observer import (
    GoalStairsServiceObserver,
)
from sandbox.metro_station_sandbox.runtime.passenger_goal_command_executor import (
    ProductionGoalCommandExecutor,
)
from sandbox.metro_station_sandbox.runtime.passenger_goal_observation import (
    ProductionGoalObservationAdapter,
)
from sandbox.metro_station_sandbox.runtime.passenger_goal_service_observer import (
    ProductionGoalServiceEventObserver,
)
from sandbox.metro_station_sandbox.planning.plan import (
    AgentIntent,
    AgentPlan,
)
from sandbox.metro_station_sandbox.planning.goal_commands import GoalCommand
from sandbox.metro_station_sandbox.planning.goal_events import GoalEventKind
from sandbox.metro_station_sandbox.runtime.passenger_goal_command_executor import (
    ProductionGoalCommandContext,
)


class GoalRuntimePortTests(unittest.TestCase):
    def test_all_observation_adapters_use_the_canonical_port(self) -> None:
        adapters = (
            GoalGateObservationAdapter(),
            GoalBoardingObservationAdapter(),
            GoalStairsObservationAdapter(),
            GoalJourneyObservationAdapter(),
            ProductionGoalObservationAdapter(),
        )

        self.assertTrue(all(isinstance(adapter, RuntimeObservationAdapter) for adapter in adapters))
        for adapter in adapters:
            self.assertEqual(
                ["self", "context", "graph", "state"],
                list(inspect.signature(type(adapter).observe).parameters),
            )

    def test_all_command_executors_use_the_canonical_port(self) -> None:
        executors = (
            GoalGateCommandExecutor(),
            GoalBoardingCommandExecutor(),
            GoalStairsCommandExecutor(),
            GoalJourneyCommandExecutor(),
            ProductionGoalCommandExecutor(),
        )

        self.assertTrue(all(isinstance(executor, CommandExecutor) for executor in executors))
        for executor in executors:
            self.assertEqual(
                ["self", "context", "commands", "current_stage"],
                list(inspect.signature(type(executor).execute).parameters),
            )

    def test_all_service_observers_use_the_canonical_port(self) -> None:
        observers = (
            GoalGateServiceObserver(),
            GoalBoardingServiceObserver(),
            GoalStairsServiceObserver(),
            GoalJourneyServiceObserver(),
            ProductionGoalServiceEventObserver(),
        )

        self.assertTrue(all(isinstance(observer, ServiceEventObserver) for observer in observers))

    def test_repository_has_no_goal_authority_boundary_violations(self) -> None:
        package_root = Path(__file__).parents[1] / "sandbox" / "metro_station_sandbox"

        violations = audit_goal_authority(package_root)

        self.assertEqual((), violations)

    def test_agent_plan_has_no_strategic_choice_actions(self) -> None:
        for intent in AgentIntent:
            plan = AgentPlan.for_intent(intent)
            self.assertFalse(hasattr(plan, "action_sequence"))
            self.assertFalse(hasattr(plan, "chosen_facilities"))
            self.assertFalse(hasattr(plan, "assign_facility"))

    def test_formal_agents_do_not_contain_legacy_choice_execution(self) -> None:
        package_root = Path(__file__).parents[1] / "sandbox" / "metro_station_sandbox"
        formal_paths = (
            "agents/passenger.py",
            "agents/staff.py",
            "agents/transit.py",
            "planning/plan.py",
        )
        for relative in formal_paths:
            source = (package_root / relative).read_text(encoding="utf-8")
            self.assertNotIn("CHOOSE_FACILITY", source, relative)
            self.assertNotIn("CHOOSE_PLATFORM", source, relative)

    def test_production_runtime_does_not_import_migration_package(self) -> None:
        package_root = Path(__file__).parents[1] / "sandbox" / "metro_station_sandbox"
        for path in package_root.rglob("*.py"):
            if "migration" in path.relative_to(package_root).parts:
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(".migration import", source, str(path))
            self.assertNotIn(".migration.", source, str(path))

    def test_train_wait_command_registers_passenger_with_platform_layout(self) -> None:
        passenger = SimpleNamespace(state="riding_vertical")
        joined: list[object] = []
        model = SimpleNamespace(join_platform=lambda item: not joined.append(item))

        events = ProductionGoalCommandExecutor().execute(
            ProductionGoalCommandContext(model=model, passenger=passenger),
            (
                GoalCommand(
                    kind="wait_for_event",
                    event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
                ),
            ),
        )

        self.assertEqual((), events)
        self.assertEqual([passenger], joined)
        self.assertEqual("riding_vertical", passenger.state)

    def test_non_train_wait_command_keeps_current_physical_waiting_state(self) -> None:
        passenger = SimpleNamespace(state="walking")
        model = SimpleNamespace(join_platform=lambda _passenger: False)

        ProductionGoalCommandExecutor().execute(
            ProductionGoalCommandContext(model=model, passenger=passenger),
            (GoalCommand(kind="wait_for_event", event_kind="alarm_cleared"),),
        )

        self.assertEqual("walking", passenger.state)


if __name__ == "__main__":
    unittest.main()
