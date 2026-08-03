from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult
from metro_station_acceptance.goal_graph_acceptance import (
    run_goal_graph_acceptance,
)
from metro_station_acceptance.goal_journey_acceptance import (
    run_four_journey_acceptance,
)


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


class GoalGraphAcceptanceTests(unittest.TestCase):
    def test_acceptance_report_requires_physical_and_graph_terminal_parity(self) -> None:
        report = run_goal_graph_acceptance(
            seed=7,
            entry_count_hour=120,
            exit_count_hour=120,
            transfer_count_hour=120,
            demand_minutes=2,
            clearance_minutes=8,
            movement_backend=InstantMovementBackend(),
        )
        self.assertEqual("ok", report.status)
        self.assertEqual(12, report.spawned_persons)
        self.assertEqual(12, report.terminal_persons)
        self.assertEqual(12, report.completed_graphs)
        self.assertGreater(report.graph_event_counts["train_available"], 0)
        self.assertEqual("pass", report.trajectory_status)
        self.assertEqual(12, report.trajectory_count)
        self.assertEqual((), report.clearance_blocker_codes)
        self.assertTrue(all(report.clearance_checks.values()))
        self.assertTrue(all(report.checks.values()))

    def test_four_journeys_clear_for_required_seeds(self) -> None:
        report = run_four_journey_acceptance(
            seeds=(41, 42, 43),
            movement_backend_factory=InstantMovementBackend,
            normal_options={
                "entry_count_hour": 120,
                "exit_count_hour": 120,
                "transfer_count_hour": 120,
                "demand_minutes": 2,
                "clearance_minutes": 25,
            },
            evacuation_persons=12,
            evacuation_minutes=3,
        )

        self.assertEqual("ok", report.status)
        self.assertEqual((41, 42, 43), report.seeds)
        self.assertTrue(all(item.status == "ok" for item in report.normal))
        self.assertTrue(all(item.status == "ok" for item in report.evacuation))
        self.assertTrue(
            all(
                set(item.terminal_by_intent)
                == {"enter_and_board", "exit_station", "transfer"}
                for item in report.normal
            )
        )
        self.assertTrue(
            all(item.evacuated_persons == 12 for item in report.evacuation)
        )


if __name__ == "__main__":
    unittest.main()
