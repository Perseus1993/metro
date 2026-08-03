from __future__ import annotations

import unittest

from scripts import run_metro_stress_matrix as stress
from sandbox.metro_station_sandbox.agents.passenger import PassengerAgent
from sandbox.metro_station_sandbox.facilities.vertical_runtime import (
    ElevatorProcessAgent,
    EscalatorProcessAgent,
)
from sandbox.metro_station_sandbox.planning.plan import AgentIntent


ELEVATOR_ID = "vertical:elevator_a:down:b1_concourse:b2_platform"
ESCALATOR_ID = "vertical:down_escalator_a:down:b1_concourse:b2_platform"


class ActiveServiceDisruptionTests(unittest.TestCase):
    def _model(self, *events: str):
        event_args = [
            item for event in events for item in ("--facility-event", event)
        ]
        args = stress.build_parser().parse_args(
            [
                "--pairs",
                "0:0",
                "--minutes",
                "2",
                "--tick-seconds",
                "1",
                "--design-template",
                "visual_demo_station",
                "--goal-graph-mode",
                "active",
                *event_args,
            ]
        )
        scenario = stress.make_scenario(args, stress.StressCase(0, 0, 42))
        return stress.MetroStationModel(scenario, seed=42)

    def _passenger(self, model) -> PassengerAgent:
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=model.step_index,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        return passenger

    def test_elevator_freezes_loaded_cabin_and_resumes_without_teleport(self) -> None:
        model = self._model(
            f"1:disable:{ELEVATOR_ID}",
            f"4:enable:{ELEVATOR_ID}",
        )
        elevator = model.facilities_by_id[ELEVATOR_ID]
        self.assertIsInstance(elevator, ElevatorProcessAgent)
        passenger = self._passenger(model)
        elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(0)
        elevator._begin_boarding([passenger], 1)
        elevator._depart_cabin()

        model.step()
        remaining_before_stop = elevator.travel_remaining_steps
        position_before_stop = passenger.pos
        arrival_before_stop = model.facility_service_events[0].arrive_time

        model.step()
        model.step()
        model.step()

        self.assertEqual(remaining_before_stop, elevator.travel_remaining_steps)
        self.assertEqual(position_before_stop, passenger.pos)
        self.assertEqual(3.0, elevator.outage_person_seconds)
        self.assertEqual(1, elevator.forced_stop_count)
        self.assertEqual(1, elevator.forced_stop_persons)
        self.assertEqual(
            arrival_before_stop + 3.0,
            model.facility_service_events[0].arrive_time,
        )
        self.assertEqual(
            1,
            model.disruption_controller.applied_events[0].active_service_persons_before,
        )

        model.step()

        self.assertEqual(remaining_before_stop - 1, elevator.travel_remaining_steps)
        self.assertNotEqual(position_before_stop, passenger.pos)
        for _ in range(elevator.cycle_steps + 2):
            model.step()

        self.assertEqual([], elevator.cabin_passengers)
        self.assertEqual(1, elevator.served_persons)
        self.assertFalse(passenger.passive_facility_service)

    def test_escalator_stop_converts_active_ride_to_slower_walk_off(self) -> None:
        model = self._model(
            f"1:disable:{ESCALATOR_ID}",
            f"7:enable:{ESCALATOR_ID}",
        )
        escalator = model.facilities_by_id[ESCALATOR_ID]
        self.assertIsInstance(escalator, EscalatorProcessAgent)
        passenger = self._passenger(model)
        passenger.pos = escalator.spec.queue_layout.slot(0)
        self.assertTrue(escalator.queue.join(passenger))
        self.assertIs(passenger, escalator.queue.pop(0))
        escalator._start_passive_ride(
            passenger,
            mode="stand",
            ride_steps=escalator._ride_steps_from_seconds(None),
        )

        model.step()
        model.step()

        ride = escalator.active_rides[0]
        self.assertGreater(ride.progress_steps, 1.0)
        self.assertLess(ride.progress_steps, 2.0)
        self.assertNotEqual(escalator.spec.position, passenger.pos)
        self.assertNotEqual(escalator.spec.exit_position, passenger.pos)
        self.assertGreater(model.facility_service_events[0].end_time, 20.0)

        while model.current_time_seconds < 35:
            model.step()

        self.assertEqual([], escalator.active_rides)
        self.assertEqual(1, escalator.served_persons)
        self.assertFalse(passenger.passive_facility_service)
        self.assertGreater(escalator.outage_person_seconds, 0.0)

    def test_disabled_elevator_finalize_preserves_stranded_cabin(self) -> None:
        model = self._model(f"1:disable:{ELEVATOR_ID}")
        elevator = model.facilities_by_id[ELEVATOR_ID]
        passenger = self._passenger(model)
        elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(0)
        elevator._begin_boarding([passenger], 1)
        elevator._depart_cabin()

        model.step()
        model.step()
        elevator.finalize()
        diagnostics = stress.active_service_disruption_diagnostics(model)
        decision = stress.assess_stress_row(
            {
                "status": "ok",
                **diagnostics,
            },
            min_completion_rate=None,
            max_final_station_persons=None,
        )

        self.assertEqual([passenger], elevator.cabin_passengers)
        self.assertTrue(passenger.passive_facility_service)
        self.assertEqual(1, diagnostics["active_service_stranded_persons_final"])
        self.assertEqual("fail", decision["acceptance_status"])


if __name__ == "__main__":
    unittest.main()
