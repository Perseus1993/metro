from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.planning.goal_commands import (
    GoalCommand,
    GoalCommandKind,
)
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.goal_engine import (
    GoalEngineResult,
    GoalStateMachine,
)
from sandbox.metro_station_sandbox.planning.goal_graph import (
    GoalNodeKind,
    JourneyGoalNode,
    JourneyGraph,
    JourneyTransition,
)
from sandbox.metro_station_sandbox.planning.goal_graph_io import (
    journey_graph_from_mapping,
    journey_graph_to_dict,
)
from sandbox.metro_station_sandbox.planning.goal_state import (
    AgentGoalState,
    FacilityCommitment,
    FacilityInteractionState,
)


class GoalContractTests(unittest.TestCase):
    def minimal_graph(self) -> JourneyGraph:
        return JourneyGraph(
            graph_id="entry_gate_vertical_slice",
            entry_node_id="enter_station",
            nodes=(
                JourneyGoalNode(
                    node_id="enter_station",
                    kind=GoalNodeKind.ENTER_REGION.value,
                    label="station entrance",
                    region_id="station_entrance",
                ),
                JourneyGoalNode(
                    node_id="pass_entry_gate",
                    kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                    label="pass entry gate",
                    facility_stage="entry_gate",
                    decision_region_id="entry_gate_decision",
                ),
                JourneyGoalNode(
                    node_id="complete",
                    kind=GoalNodeKind.COMPLETE.value,
                    label="paid hall reached",
                ),
            ),
            transitions=(
                JourneyTransition(
                    transition_id="entrance_to_gate",
                    source_node_id="enter_station",
                    target_node_id="pass_entry_gate",
                    event_kind=GoalEventKind.GOAL_COMPLETED.value,
                ),
                JourneyTransition(
                    transition_id="gate_to_complete",
                    source_node_id="pass_entry_gate",
                    target_node_id="complete",
                    event_kind=GoalEventKind.GOAL_COMPLETED.value,
                ),
            ),
        )

    def test_journey_graph_round_trips_through_mapping(self) -> None:
        graph = self.minimal_graph()

        restored = journey_graph_from_mapping(journey_graph_to_dict(graph))

        self.assertEqual(graph, restored)
        self.assertEqual("pass_entry_gate", graph.outgoing("enter_station")[0].target_node_id)

    def test_journey_graph_rejects_unreachable_goal(self) -> None:
        graph = self.minimal_graph()
        with self.assertRaisesRegex(ValueError, "unreachable journey goals"):
            JourneyGraph(
                graph_id=graph.graph_id,
                entry_node_id=graph.entry_node_id,
                nodes=(
                    *graph.nodes,
                    JourneyGoalNode(
                        node_id="orphan",
                        kind=GoalNodeKind.ENTER_REGION.value,
                        label="orphan",
                        region_id="nowhere",
                    ),
                ),
                transitions=graph.transitions,
            )

    def test_facility_goal_requires_decision_region(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires decision_region_id"):
            JourneyGoalNode(
                node_id="gate",
                kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                label="gate",
                facility_stage="entry_gate",
            )

    def test_agent_goal_state_keeps_commitment_and_queue_consistent(self) -> None:
        commitment = FacilityCommitment(
            facility_id="gate_3",
            committed_at_seconds=12.0,
            reason="generalized_cost_logit",
            reconsider_after_seconds=27.0,
        )
        state = AgentGoalState(
            journey_graph_id="entry_gate_vertical_slice",
            journey_graph_version=1,
            current_node_id="pass_entry_gate",
            interaction_state=FacilityInteractionState.QUEUEING.value,
            current_stage="entry_gate",
            commitment=commitment,
            queued_facility_id="gate_3",
        )

        self.assertEqual("gate_3", state.as_dict()["commitment"]["facility_id"])
        with self.assertRaisesRegex(ValueError, "must match committed"):
            AgentGoalState(
                journey_graph_id=state.journey_graph_id,
                journey_graph_version=1,
                current_node_id=state.current_node_id,
                interaction_state=FacilityInteractionState.QUEUEING.value,
                commitment=commitment,
                queued_facility_id="gate_4",
            )

    def test_decision_observation_rejects_duplicate_candidates(self) -> None:
        candidate = FacilityObservation(
            facility_id="gate_1",
            stage="entry_gate",
            available=True,
            reachable=True,
            walking_time_seconds=4.0,
            queue_persons=2,
            estimated_wait_seconds=8.0,
        )
        with self.assertRaisesRegex(ValueError, "duplicate facility candidates"):
            DecisionObservation(
                time_seconds=10.0,
                current_region_id="entry_gate_decision",
                candidates=(candidate, candidate),
            )

    def test_goal_event_and_command_require_target_contracts(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires region_id"):
            GoalEvent(kind=GoalEventKind.ENTERED_REGION.value, time_seconds=2.0)
        with self.assertRaisesRegex(ValueError, "requires target_region_id"):
            GoalCommand(kind=GoalCommandKind.WALK_TO_REGION.value)

        command = GoalCommand(
            kind=GoalCommandKind.SELECT_FACILITY.value,
            facility_id="gate_2",
            reason="shortest perceived delay",
        )
        self.assertEqual("gate_2", command.as_dict()["facility_id"])

    def test_goal_state_machine_contract_is_framework_independent(self) -> None:
        class ContractOnlyMachine:
            def start(self, graph, *, at_time_seconds=0.0):
                return GoalEngineResult(
                    state=AgentGoalState(
                        journey_graph_id=graph.graph_id,
                        journey_graph_version=graph.version,
                        current_node_id=graph.entry_node_id,
                    )
                )

            def handle(self, graph, state, event):
                return GoalEngineResult(state=state)

        machine = ContractOnlyMachine()
        result = machine.start(self.minimal_graph())

        self.assertIsInstance(machine, GoalStateMachine)
        self.assertEqual("enter_station", result.state.current_node_id)


if __name__ == "__main__":
    unittest.main()
