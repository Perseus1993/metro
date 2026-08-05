from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.planning.default_goal_state_machine import (
    EventDrivenGoalStateMachine,
)
from sandbox.metro_station_sandbox.planning.goal_commands import GoalCommandKind
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.goal_state import FacilityInteractionState
from sandbox.metro_station_sandbox.planning.journeys import entry_gate_journey_graph


class EntryGateGoalStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = entry_gate_journey_graph()
        self.machine = EventDrivenGoalStateMachine()

    def candidates(self, *, gate_2_available: bool = True) -> DecisionObservation:
        return DecisionObservation(
            time_seconds=6.0,
            current_region_id="entry_gate_decision",
            entered_region_ids=("entry_gate_decision",),
            candidates=(
                FacilityObservation(
                    facility_id="gate_1",
                    stage="entry_gate",
                    available=True,
                    reachable=True,
                    walking_time_seconds=5.0,
                    queue_persons=2,
                    estimated_wait_seconds=9.0,
                ),
                FacilityObservation(
                    facility_id="gate_2",
                    stage="entry_gate",
                    available=gate_2_available,
                    reachable=True,
                    walking_time_seconds=4.0,
                    queue_persons=1,
                    estimated_wait_seconds=3.0,
                ),
            ),
        )

    def enter_decision_region(self):
        started = self.machine.start(self.graph)
        return self.machine.handle(
            self.graph,
            started.state,
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=5.0,
                region_id="entry_gate_decision",
            ),
        )

    def choose_gate(self):
        decision = self.enter_decision_region()
        return self.machine.handle(
            self.graph,
            decision.state,
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=6.0,
                observation=self.candidates(),
            ),
        )

    def test_start_has_only_fuzzy_region_goal(self) -> None:
        result = self.machine.start(self.graph)

        self.assertEqual("approach_entry_gate_decision", result.state.current_node_id)
        self.assertIsNone(result.state.commitment)
        self.assertEqual(GoalCommandKind.WALK_TO_REGION.value, result.commands[0].kind)
        self.assertEqual("entry_gate_decision", result.commands[0].target_region_id)

    def test_gate_is_selected_only_after_entering_decision_region(self) -> None:
        decision = self.enter_decision_region()

        self.assertEqual("use_entry_gate", decision.state.current_node_id)
        self.assertEqual(
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            decision.state.interaction_state,
        )
        self.assertIsNone(decision.state.commitment)

        selected = self.machine.handle(
            self.graph,
            decision.state,
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=6.0,
                observation=self.candidates(),
            ),
        )

        self.assertEqual("gate_2", selected.state.commitment.facility_id)
        self.assertEqual(
            FacilityInteractionState.APPROACH_QUEUE.value,
            selected.state.interaction_state,
        )
        self.assertEqual(
            [GoalCommandKind.SELECT_FACILITY.value, GoalCommandKind.WALK_TO_QUEUE.value],
            [command.kind for command in selected.commands],
        )

    def test_candidate_updates_do_not_break_an_active_commitment(self) -> None:
        selected = self.choose_gate()

        repeated = self.machine.handle(
            self.graph,
            selected.state,
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=7.0,
                observation=self.candidates(),
            ),
        )

        self.assertFalse(repeated.handled)
        self.assertEqual(selected.state, repeated.state)

    def test_queue_and_service_events_complete_entry_gate_goal(self) -> None:
        selected = self.choose_gate()
        captured = self.machine.handle(
            self.graph,
            selected.state,
            GoalEvent(
                kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                time_seconds=8.0,
                facility_id="gate_2",
            ),
        )
        queued = self.machine.handle(
            self.graph,
            captured.state,
            GoalEvent(
                kind=GoalEventKind.QUEUE_JOINED.value,
                time_seconds=9.0,
                facility_id="gate_2",
            ),
        )
        serving = self.machine.handle(
            self.graph,
            queued.state,
            GoalEvent(
                kind=GoalEventKind.SERVICE_STARTED.value,
                time_seconds=10.0,
                facility_id="gate_2",
            ),
        )
        released = self.machine.handle(
            self.graph,
            serving.state,
            GoalEvent(
                kind=GoalEventKind.SERVICE_COMPLETED.value,
                time_seconds=11.0,
                facility_id="gate_2",
            ),
        )

        self.assertEqual(FacilityInteractionState.CAPTURE_QUEUE.value, captured.state.interaction_state)
        self.assertEqual("gate_2", queued.state.queued_facility_id)
        self.assertEqual(FacilityInteractionState.IN_SERVICE.value, serving.state.interaction_state)
        self.assertEqual("enter_paid_hall", released.state.current_node_id)
        self.assertIsNone(released.state.commitment)
        self.assertEqual(GoalCommandKind.WALK_TO_REGION.value, released.commands[0].kind)

        complete = self.machine.handle(
            self.graph,
            released.state,
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=12.0,
                region_id="paid_hall",
            ),
        )
        self.assertEqual("complete", complete.state.current_node_id)
        self.assertEqual(3, complete.state.transition_count)
        self.assertEqual(
            (GoalCommandKind.COMPLETE_JOURNEY.value,),
            tuple(command.kind for command in complete.commands),
        )

    def test_unavailable_gate_enters_replan_and_selects_an_alternative(self) -> None:
        selected = self.choose_gate()
        replan = self.machine.handle(
            self.graph,
            selected.state,
            GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=7.0,
                facility_id="gate_2",
                reason="gate_closed",
            ),
        )

        self.assertEqual(FacilityInteractionState.REPLAN_PENDING.value, replan.state.interaction_state)
        self.assertIsNone(replan.state.commitment)
        self.assertEqual(1, replan.state.retry_count)
        self.assertEqual(GoalCommandKind.REPLAN_STAGE.value, replan.commands[0].kind)

        alternative = self.machine.handle(
            self.graph,
            replan.state,
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=8.0,
                observation=self.candidates(gate_2_available=False),
            ),
        )
        self.assertEqual("gate_1", alternative.state.commitment.facility_id)

    def test_no_eligible_gate_keeps_passenger_uncommitted(self) -> None:
        decision = self.enter_decision_region()
        observation = DecisionObservation(
            time_seconds=6.0,
            current_region_id="entry_gate_decision",
            candidates=(),
        )

        result = self.machine.handle(
            self.graph,
            decision.state,
            GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=6.0,
                observation=observation,
            ),
        )

        self.assertIsNone(result.state.commitment)
        self.assertEqual(
            FacilityInteractionState.WAITING_CAPACITY.value,
            result.state.interaction_state,
        )
        self.assertEqual("no_eligible_facility", result.commands[0].reason)


if __name__ == "__main__":
    unittest.main()
