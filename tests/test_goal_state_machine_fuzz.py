from __future__ import annotations

import random
import unittest

from sandbox.metro_station_sandbox.planning.default_goal_state_machine import (
    EventDrivenGoalStateMachine,
)
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.journeys import entry_gate_journey_graph


class GoalStateMachineFuzzTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = entry_gate_journey_graph()

    def random_observation(self, rng: random.Random, time_seconds: float) -> DecisionObservation:
        candidates = tuple(
            FacilityObservation(
                facility_id=f"gate_{index}",
                stage="entry_gate" if rng.random() > 0.1 else "exit_gate",
                available=rng.random() > 0.2,
                reachable=rng.random() > 0.1,
                walking_time_seconds=rng.random() * 20,
                queue_persons=rng.randint(0, 50),
                estimated_wait_seconds=rng.random() * 90,
                local_density_persons_m2=rng.random() * 6,
            )
            for index in range(rng.randint(0, 10))
        )
        return DecisionObservation(
            time_seconds=time_seconds,
            current_region_id=rng.choice(
                ("entry_gate_decision", "paid_hall", "wrong_region")
            ),
            candidates=candidates,
        )

    def random_event(self, rng: random.Random, time_seconds: float) -> GoalEvent:
        kind = rng.choice(tuple(GoalEventKind))
        if kind == GoalEventKind.ENTERED_REGION:
            return GoalEvent(
                kind=kind.value,
                time_seconds=time_seconds,
                region_id=rng.choice(("entry_gate_decision", "paid_hall", "wrong_region")),
            )
        if kind == GoalEventKind.CANDIDATES_UPDATED:
            return GoalEvent(
                kind=kind.value,
                time_seconds=time_seconds,
                observation=self.random_observation(rng, time_seconds),
            )
        if kind in {
            GoalEventKind.REACHED_QUEUE_CAPTURE,
            GoalEventKind.QUEUE_JOINED,
            GoalEventKind.SERVICE_STARTED,
            GoalEventKind.SERVICE_COMPLETED,
            GoalEventKind.FACILITY_UNAVAILABLE,
        }:
            return GoalEvent(
                kind=kind.value,
                time_seconds=time_seconds,
                facility_id=f"gate_{rng.randint(0, 12)}",
                reason="random_event",
            )
        return GoalEvent(kind=kind.value, time_seconds=time_seconds, reason="random_event")

    def assert_state_invariants(self, previous, result, event) -> None:
        state = result.state
        self.graph.node(state.current_node_id)
        self.assertEqual(self.graph.graph_id, state.journey_graph_id)
        self.assertEqual(self.graph.version, state.journey_graph_version)
        self.assertGreaterEqual(state.transition_count, previous.transition_count)
        self.assertGreaterEqual(state.retry_count, previous.retry_count)
        if result.handled:
            self.assertEqual(event.time_seconds, state.last_event_time_seconds)
        else:
            self.assertEqual(previous, state)
        if state.queued_facility_id is not None:
            self.assertIsNotNone(state.commitment)
            self.assertEqual(state.commitment.facility_id, state.queued_facility_id)
        for command in result.commands:
            self.assertTrue(command.kind)

    def test_twenty_thousand_random_events_preserve_invariants(self) -> None:
        for seed in range(100):
            rng = random.Random(seed)
            machine = EventDrivenGoalStateMachine()
            state = machine.start(self.graph).state
            time_seconds = 0.0
            for _ in range(200):
                time_seconds += rng.random() * 3 + 0.001
                event = self.random_event(rng, time_seconds)
                result = machine.handle(self.graph, state, event)
                self.assert_state_invariants(state, result, event)
                state = result.state

    def test_randomized_valid_journeys_always_complete(self) -> None:
        for seed in range(250):
            rng = random.Random(10_000 + seed)
            machine = EventDrivenGoalStateMachine()
            state = machine.start(self.graph).state
            time_seconds = rng.random()

            time_seconds += rng.random() + 0.01
            state = machine.handle(
                self.graph,
                state,
                GoalEvent(
                    kind=GoalEventKind.ENTERED_REGION.value,
                    time_seconds=time_seconds,
                    region_id="entry_gate_decision",
                ),
            ).state
            time_seconds += rng.random() + 0.01
            observation = self.random_observation_with_eligible_gate(rng, time_seconds)
            selected = machine.handle(
                self.graph,
                state,
                GoalEvent(
                    kind=GoalEventKind.CANDIDATES_UPDATED.value,
                    time_seconds=time_seconds,
                    observation=observation,
                ),
            )
            state = selected.state
            facility_id = state.commitment.facility_id

            for kind in (
                GoalEventKind.REACHED_QUEUE_CAPTURE,
                GoalEventKind.QUEUE_JOINED,
                GoalEventKind.SERVICE_STARTED,
                GoalEventKind.SERVICE_COMPLETED,
            ):
                time_seconds += rng.random() + 0.01
                state = machine.handle(
                    self.graph,
                    state,
                    GoalEvent(
                        kind=kind.value,
                        time_seconds=time_seconds,
                        facility_id=facility_id,
                    ),
                ).state
            time_seconds += rng.random() + 0.01
            result = machine.handle(
                self.graph,
                state,
                GoalEvent(
                    kind=GoalEventKind.ENTERED_REGION.value,
                    time_seconds=time_seconds,
                    region_id="paid_hall",
                ),
            )
            with self.subTest(seed=seed):
                self.assertEqual("complete", result.state.current_node_id)
                self.assertEqual(3, result.state.transition_count)

    def random_observation_with_eligible_gate(
        self,
        rng: random.Random,
        time_seconds: float,
    ) -> DecisionObservation:
        candidates = list(self.random_observation(rng, time_seconds).candidates)
        candidates.append(
            FacilityObservation(
                facility_id="guaranteed_gate",
                stage="entry_gate",
                available=True,
                reachable=True,
                walking_time_seconds=1,
                queue_persons=0,
                estimated_wait_seconds=1,
            )
        )
        return DecisionObservation(
            time_seconds=time_seconds,
            current_region_id="entry_gate_decision",
            candidates=tuple(candidates),
        )


if __name__ == "__main__":
    unittest.main()
