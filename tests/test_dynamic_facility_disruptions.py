from __future__ import annotations

import unittest

from scripts import run_metro_stress_matrix as stress
from scripts import run_metro_emergency_matrix as emergency
from scripts import run_metro_emergency_sensitivity as sensitivity
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.plan import AgentIntent


LANE_1 = "entry_gate:gate_bank_a:lane_1"
OTHER_ENTRY_LANES = tuple(
    f"entry_gate:gate_bank_a:lane_{lane}" for lane in range(2, 7)
)


def _commit_and_queue(passenger, facility) -> None:
    _commit_for_facility(passenger, facility)
    runtime = passenger.goal_runtime
    runtime.handle(
        GoalEvent(
            kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
            time_seconds=0.0,
            facility_id=facility.facility_id,
        )
    )
    facility.join_queue(passenger, authority="goal_graph")
    runtime.handle(
        GoalEvent(
            kind=GoalEventKind.QUEUE_JOINED.value,
            time_seconds=0.0,
            facility_id=facility.facility_id,
        )
    )


def _commit_for_facility(passenger, facility) -> None:
    runtime = passenger.goal_runtime
    runtime.handle(
        GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=0.0,
            region_id="entry_gate_decision",
        )
    )
    runtime.handle(
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=0.0,
            observation=DecisionObservation(
                time_seconds=0.0,
                current_region_id="entry_gate_decision",
                entered_region_ids=("entry_gate_decision",),
                candidates=(
                    FacilityObservation(
                        facility_id=facility.facility_id,
                        stage=facility.spec.stage,
                        available=True,
                        reachable=True,
                        walking_time_seconds=0.0,
                        queue_persons=0,
                        estimated_wait_seconds=0.0,
                    ),
                ),
            ),
        )
    )
    passenger.assigned_facility_id = facility.facility_id


class DynamicFacilityDisruptionTests(unittest.TestCase):
    def _args(self, *extra: str):
        return stress.build_parser().parse_args(
            [
                "--pairs",
                "0:0",
                "--minutes",
                "2",
                "--tick-seconds",
                "5",
                "--design-template",
                "visual_demo_station",
                "--goal-graph-mode",
                "active",
                "--clock-mode",
                "physical",
                *extra,
            ]
        )

    def _model(self, *extra: str):
        args = self._args(*extra)
        case = stress.StressCase(0, 0, 42)
        return stress.MetroStationModel(stress.make_scenario(args, case), seed=42)

    def test_cli_parser_preserves_colons_in_facility_id(self) -> None:
        event = stress.parse_facility_event(f"30:disable:{LANE_1}")

        self.assertEqual(30, event.at_seconds)
        self.assertEqual("disable", event.action)
        self.assertEqual(LANE_1, event.facility_id)

    def test_schedule_rejects_unaligned_out_of_order_and_invalid_lifecycle(self) -> None:
        invalid_schedules = (
            ("7:disable:" + LANE_1,),
            ("10:disable:" + LANE_1, "5:enable:" + LANE_1),
            ("10:enable:" + LANE_1,),
            ("10:disable:" + LANE_1, "15:disable:" + LANE_1),
            ("120:disable:" + LANE_1,),
        )

        for schedule in invalid_schedules:
            cli = [item for event in schedule for item in ("--facility-event", event)]
            with self.subTest(schedule=schedule):
                args = self._args(*cli)
                with self.assertRaises(ValueError):
                    stress.make_scenario(args, stress.StressCase(0, 0, 42))

    def test_unknown_dynamic_facility_fails_at_model_startup(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown facilities"):
            self._model("--facility-event", "0:disable:missing:facility")

    def test_disable_replans_queued_passenger_to_available_lane(self) -> None:
        model = self._model("--facility-event", f"0:disable:{LANE_1}")
        disrupted = model.facilities_by_id[LANE_1]
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        _commit_and_queue(passenger, disrupted)

        model.step()

        event = model.disruption_controller.applied_events[0]
        self.assertTrue(disrupted.is_forced_disabled)
        self.assertNotIn(passenger, disrupted.queue)
        self.assertNotEqual(LANE_1, passenger.assigned_facility_id)
        self.assertEqual(1, event.queue_persons_before)
        self.assertEqual(1, event.passengers_replanned)
        self.assertEqual(f"facility_disabled:{LANE_1}", passenger.last_replan_reason)

    def test_disable_replans_all_pre_service_commitment_states(self) -> None:
        for state_name in ("approach_queue", "capture_queue", "queueing"):
            with self.subTest(state_name=state_name):
                model = self._model("--facility-event", f"0:disable:{LANE_1}")
                disrupted = model.facilities_by_id[LANE_1]
                passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
                _commit_for_facility(passenger, disrupted)
                if state_name in {"capture_queue", "queueing"}:
                    passenger.goal_runtime.handle(
                        GoalEvent(
                            kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                            time_seconds=0.0,
                            facility_id=disrupted.facility_id,
                        )
                    )
                if state_name == "queueing":
                    disrupted.join_queue(passenger, authority="goal_graph")
                    passenger.goal_runtime.handle(
                        GoalEvent(
                            kind=GoalEventKind.QUEUE_JOINED.value,
                            time_seconds=0.0,
                            facility_id=disrupted.facility_id,
                        )
                    )
                old_terminal = None
                if state_name == "approach_queue":
                    stage = disrupted.spec.stage
                    model._reserve_facility_approach_slot(passenger, disrupted)
                    route = model.route_to_facility_queue(passenger, disrupted)
                    passenger.set_route(
                        route,
                        goal_kind="queue_approach",
                        goal_label="closure integration fixture",
                        facility_id=disrupted.facility_id,
                        stage=stage,
                    )
                    old_terminal = route[-1]
                    self.assertEqual(
                        disrupted.facility_id,
                        passenger.facility_approach_facility_ids_by_stage[stage],
                    )
                    self.assertIn(
                        int(passenger.unique_id),
                        model._facility_targeting_reservations[disrupted.facility_id],
                    )
                self.assertEqual(
                    state_name,
                    passenger.goal_runtime.state.interaction_state,
                )

                model.disruption_controller.apply_due(model)

                event = model.disruption_controller.applied_events[0]
                commitment = passenger.goal_runtime.state.commitment
                self.assertEqual(1, event.passengers_replanned)
                self.assertTrue(
                    commitment is None or commitment.facility_id != LANE_1
                )
                self.assertNotIn(passenger, disrupted.queue)
                self.assertNotIn(
                    int(passenger.unique_id),
                    model._facility_targeting_reservations[disrupted.facility_id],
                )
                if old_terminal is not None:
                    stage = disrupted.spec.stage
                    self.assertNotEqual(
                        disrupted.facility_id,
                        passenger.facility_approach_facility_ids_by_stage.get(stage),
                    )
                    terminal = (
                        passenger.route[-1]
                        if passenger.route
                        else passenger.target
                    )
                    self.assertNotEqual(old_terminal, terminal)
                self.assertEqual(
                    f"facility_disabled:{LANE_1}",
                    passenger.last_replan_reason,
                )

    def test_real_coordinator_closure_retargets_route_and_reservation_atomically(self) -> None:
        model = self._model("--facility-event", f"0:disable:{LANE_1}")
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        model.goal_coordinator.handle(
            passenger,
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=0.0,
                region_id="entry_gate_decision",
            ),
        )
        commitment = passenger.goal_runtime.state.commitment
        self.assertIsNotNone(commitment)
        self.assertEqual(LANE_1, commitment.facility_id)
        disrupted = model.facilities_by_id[LANE_1]
        passenger_id = int(passenger.unique_id)
        old_terminal = passenger.route[-1] if passenger.route else passenger.target
        self.assertIsNotNone(
            disrupted.queue.approach_slot_reservation(passenger_id)
        )

        model.disruption_controller.apply_due(model)

        replacement = passenger.goal_runtime.state.commitment
        self.assertIsNotNone(replacement)
        self.assertNotEqual(LANE_1, replacement.facility_id)
        self.assertIsNone(
            disrupted.queue.approach_slot_reservation(passenger_id)
        )
        self.assertNotEqual(
            old_terminal,
            passenger.route[-1] if passenger.route else passenger.target,
        )
        self.assertEqual(
            1,
            model.disruption_controller.applied_events[0].passengers_replanned,
        )

    def test_disabled_lane_does_not_serve_and_resumes_on_enable(self) -> None:
        static_args = [
            value
            for facility_id in OTHER_ENTRY_LANES
            for value in ("--disable-facility", facility_id)
        ]
        model = self._model(
            *static_args,
            "--facility-event",
            f"0:disable:{LANE_1}",
            "--facility-event",
            f"10:enable:{LANE_1}",
        )
        lane = model.facilities_by_id[LANE_1]
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        lane.join_queue(passenger, authority="goal_graph")
        passenger.pos = lane._safe_queue_slot(0)

        model.step()
        model.step()

        self.assertEqual(0, lane.served_persons)
        self.assertIn(passenger, lane.queue)
        self.assertTrue(lane.is_forced_disabled)

        model.step()

        self.assertFalse(lane.is_forced_disabled)
        self.assertEqual(0, lane.served_persons)
        self.assertNotIn(passenger, lane.queue)
        self.assertTrue(lane.has_active_service(passenger))
        for _ in range(10):
            model.step()
            if not lane.has_active_service(passenger):
                break

        self.assertEqual(1, lane.served_persons)
        self.assertNotIn(passenger, lane.queue)
        self.assertFalse(lane.has_active_service(passenger))
        self.assertEqual(
            0,
            model.disruption_controller.service_start_violations(
                model.facility_service_events
            ),
        )
        self.assertEqual(
            ["disable", "enable"],
            [event.action for event in model.disruption_controller.applied_events],
        )

    def test_closure_boundary_respects_previously_committed_gate_pass(self) -> None:
        model = self._model("--facility-event", f"5:disable:{LANE_1}")
        lane = model.facilities_by_id[LANE_1]
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)
        _commit_and_queue(passenger, lane)
        passenger.pos = lane._safe_queue_slot(0)

        model.step()
        service_event = model.facility_service_events[0]
        self.assertEqual(0.0, service_event.commit_time)
        self.assertEqual(5.0, service_event.start_time)
        self.assertTrue(lane.has_active_service(passenger))

        model.step()

        applied = model.disruption_controller.applied_events[0]
        self.assertEqual(1, applied.active_service_persons_before)
        self.assertEqual(0, applied.passengers_replanned)
        self.assertEqual(
            "in_service",
            passenger.goal_runtime.state.interaction_state,
        )
        self.assertEqual(
            0,
            model.disruption_controller.service_start_violations(
                model.facility_service_events
            ),
        )

    def test_same_time_closures_apply_atomically_without_replan_thrashing(self) -> None:
        lane_2 = "entry_gate:gate_bank_a:lane_2"
        static_args = [
            value
            for facility_id in OTHER_ENTRY_LANES[1:]
            for value in ("--disable-facility", facility_id)
        ]
        model = self._model(
            *static_args,
            "--facility-event",
            f"0:disable:{LANE_1}",
            "--facility-event",
            f"0:disable:{lane_2}",
        )
        facilities = [model.facilities_by_id[LANE_1], model.facilities_by_id[lane_2]]
        passengers = [
            model._spawn_passenger(AgentIntent.ENTER_AND_BOARD) for _ in facilities
        ]
        for facility, passenger in zip(facilities, passengers, strict=True):
            facility.join_queue(passenger, authority="goal_graph")

        model.step()

        self.assertTrue(all(facility.is_forced_disabled for facility in facilities))
        self.assertTrue(
            all(passenger in facility.queue for facility, passenger in zip(facilities, passengers))
        )
        self.assertEqual(
            [0, 0],
            [
                event.passengers_replanned
                for event in model.disruption_controller.applied_events
            ],
        )

    def test_failed_replan_restores_goal_commitment_until_facility_recovers(self) -> None:
        args = sensitivity.build_parser().parse_args(
            ["--population", "10", "--minutes", "15"]
        )
        scenario_args = sensitivity.emergency_args(
            args,
            "escalator_stop_seconds",
            75,
        )

        row = emergency.run_case(scenario_args, emergency.EmergencyCase(10, 42))

        self.assertEqual(1.0, row["completion_rate"])
        self.assertEqual(0, row["remaining_persons"])

    def test_service_violation_is_an_acceptance_failure_without_other_thresholds(self) -> None:
        decision = stress.assess_stress_row(
            {
                "status": "ok",
                "facility_service_start_violations": 1,
            },
            min_completion_rate=None,
            max_final_station_persons=None,
        )

        self.assertEqual("fail", decision["acceptance_status"])
        self.assertIn("disabled intervals", decision["acceptance_issues"][0])


if __name__ == "__main__":
    unittest.main()
