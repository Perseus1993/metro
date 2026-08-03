from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult
from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from metro_station_acceptance.operational_acceptance import (
    run_operational_acceptance,
)
from metro_station_acceptance.operational_acceptance_scenarios import (
    CONGESTED,
    FACILITY_CLOSURE_RECOVERY,
    SINGLE_FACILITY,
    TRAIN_FULL_RECOVERY,
    TRAIN_OUTAGE_RECOVERY,
    operational_scenario,
)
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel


JPS_AVAILABLE = JuPedSimAdapter().status.available


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


class OperationalAcceptanceTests(unittest.TestCase):
    def test_boarding_queue_and_platform_waiting_never_dual_own_a_passenger(self) -> None:
        scenario = operational_scenario(TRAIN_FULL_RECOVERY)
        model = MetroStationModel(
            scenario,
            seed=42,
            movement_backend=InstantMovementBackend(),
        )
        model.running = True

        while model.running:
            model.step()
            platform_owned = {
                int(passenger.unique_id)
                for platform in model.platforms
                for passenger in platform.waiting
            }
            door_owned = {
                int(passenger.unique_id)
                for door in model.boarding_doors
                for passenger in door.queue
            }
            self.assertFalse(platform_owned & door_owned)

        self.assertFalse(model.passengers)

    def test_single_congested_full_and_outage_scenarios_clear(self) -> None:
        scenario_ids = (
            SINGLE_FACILITY,
            CONGESTED,
            TRAIN_FULL_RECOVERY,
            TRAIN_OUTAGE_RECOVERY,
        )
        for scenario_id in scenario_ids:
            with self.subTest(scenario_id=scenario_id):
                report = run_operational_acceptance(
                    scenario_id,
                    seed=42,
                    movement_backend=InstantMovementBackend(),
                )
                self.assertEqual("ok", report.status, report.as_dict())
                self.assertEqual(report.spawned_persons, report.terminal_persons)
                self.assertEqual(report.spawned_persons, report.trajectory_count)
                self.assertEqual((), report.clearance_blocker_codes)
                self.assertTrue(report.checks["no_replan_during_service"])

    @unittest.skipUnless(JPS_AVAILABLE, "JuPedSim is unavailable")
    def test_real_jupedsim_recovery_scenarios_clear_for_required_seeds(self) -> None:
        for scenario_id in (FACILITY_CLOSURE_RECOVERY, TRAIN_FULL_RECOVERY):
            for seed in (41, 42, 43):
                with self.subTest(scenario_id=scenario_id, seed=seed):
                    report = run_operational_acceptance(scenario_id, seed=seed)
                self.assertEqual("ok", report.status, report.as_dict())
                if scenario_id == FACILITY_CLOSURE_RECOVERY:
                    self.assertTrue(report.checks["pre_service_replan_exercised"])
                    self.assertTrue(report.checks["graph_replan_exercised"])
                if scenario_id == TRAIN_FULL_RECOVERY:
                    self.assertTrue(report.checks["train_full_exercised"])
                    self.assertTrue(report.checks["later_train_completed_journey"])
                self.assertTrue(report.checks["no_service_started_while_disabled"])
                self.assertTrue(report.checks["no_replan_during_service"])
                self.assertEqual(report.spawned_persons, report.terminal_persons)
                self.assertEqual(report.spawned_persons, report.trajectory_count)


if __name__ == "__main__":
    unittest.main()
