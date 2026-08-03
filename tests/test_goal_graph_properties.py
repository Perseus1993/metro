from __future__ import annotations

import json
import unittest
from dataclasses import replace

from sandbox.metro_station_sandbox.planning.goal_events import GoalEventKind
from sandbox.metro_station_sandbox.planning.goal_graph import (
    GoalNodeKind,
    JourneyGoalNode,
    JourneyTransition,
)
from sandbox.metro_station_sandbox.planning.goal_graph_io import (
    journey_graph_from_mapping,
    journey_graph_to_dict,
)
from sandbox.metro_station_sandbox.planning.journeys import entry_gate_journey_graph


class GoalGraphPropertyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = entry_gate_journey_graph()

    def test_json_round_trip_is_stable(self) -> None:
        payload = journey_graph_to_dict(self.graph)
        for _ in range(25):
            payload = json.loads(json.dumps(payload))
            restored = journey_graph_from_mapping(payload)
            self.assertEqual(self.graph, restored)
            payload = journey_graph_to_dict(restored)

    def test_every_node_is_reachable_from_entry(self) -> None:
        reached = {self.graph.entry_node_id}
        frontier = [self.graph.entry_node_id]
        while frontier:
            for transition in self.graph.outgoing(frontier.pop()):
                if transition.target_node_id in reached:
                    continue
                reached.add(transition.target_node_id)
                frontier.append(transition.target_node_id)

        self.assertEqual({node.node_id for node in self.graph.nodes}, reached)

    def test_unknown_node_lookup_and_outgoing_fail_explicitly(self) -> None:
        for operation in (self.graph.node, self.graph.outgoing):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(KeyError, "unknown journey goal"):
                    operation("missing")

    def test_duplicate_node_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate journey goal node"):
            replace(self.graph, nodes=(*self.graph.nodes, self.graph.nodes[0]))

    def test_duplicate_transition_is_rejected(self) -> None:
        duplicate = replace(
            self.graph.transitions[0],
            source_node_id="enter_paid_hall",
            target_node_id="complete",
        )
        with self.assertRaisesRegex(ValueError, "duplicate journey transition"):
            replace(self.graph, transitions=(*self.graph.transitions, duplicate))

    def test_missing_entry_and_edge_endpoints_are_rejected(self) -> None:
        cases = (
            (replace, {"entry_node_id": "missing"}, "entry node"),
            (
                replace,
                {
                    "transitions": (
                        replace(self.graph.transitions[0], source_node_id="missing"),
                        *self.graph.transitions[1:],
                    )
                },
                "source.*does not exist",
            ),
            (
                replace,
                {
                    "transitions": (
                        replace(self.graph.transitions[0], target_node_id="missing"),
                        *self.graph.transitions[1:],
                    )
                },
                "target.*does not exist",
            ),
        )
        for factory, kwargs, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ValueError, pattern):
                    factory(self.graph, **kwargs)

    def test_unreachable_node_and_missing_complete_are_rejected(self) -> None:
        orphan = JourneyGoalNode(
            node_id="orphan",
            kind=GoalNodeKind.ENTER_REGION.value,
            label="orphan",
            region_id="orphan",
        )
        with self.assertRaisesRegex(ValueError, "unreachable journey goals"):
            replace(self.graph, nodes=(*self.graph.nodes, orphan))

        without_complete = tuple(
            node for node in self.graph.nodes if node.kind != GoalNodeKind.COMPLETE.value
        )
        surviving_ids = {node.node_id for node in without_complete}
        transitions = tuple(
            edge
            for edge in self.graph.transitions
            if edge.source_node_id in surviving_ids and edge.target_node_id in surviving_ids
        )
        with self.assertRaisesRegex(ValueError, "requires at least one complete"):
            replace(self.graph, nodes=without_complete, transitions=transitions)

    def test_complete_node_cannot_have_outgoing_transition(self) -> None:
        edge = JourneyTransition(
            transition_id="illegal_restart",
            source_node_id="complete",
            target_node_id=self.graph.entry_node_id,
            event_kind=GoalEventKind.GOAL_COMPLETED.value,
        )
        with self.assertRaisesRegex(ValueError, "cannot have outgoing"):
            replace(self.graph, transitions=(*self.graph.transitions, edge))

    def test_node_contract_matrix_rejects_missing_required_fields(self) -> None:
        cases = (
            (
                dict(node_id="region", kind="enter_region", label="region"),
                "requires region_id",
            ),
            (
                dict(node_id="facility", kind="use_facility_stage", label="facility"),
                "requires facility_stage",
            ),
            (
                dict(
                    node_id="facility",
                    kind="use_facility_stage",
                    label="facility",
                    facility_stage="entry_gate",
                ),
                "requires decision_region_id",
            ),
            (
                dict(node_id="wait", kind="wait_for_event", label="wait"),
                "requires wait_event_kind",
            ),
            (
                dict(node_id="bad", kind="not_supported", label="bad"),
                "unsupported journey goal kind",
            ),
        )
        for kwargs, pattern in cases:
            with self.subTest(kind=kwargs["kind"]):
                with self.assertRaisesRegex(ValueError, pattern):
                    JourneyGoalNode(**kwargs)

    def test_cycles_are_allowed_when_all_nodes_remain_reachable(self) -> None:
        retry = JourneyTransition(
            transition_id="retry_gate",
            source_node_id="enter_paid_hall",
            target_node_id="use_entry_gate",
            event_kind="retry",
        )
        graph = replace(self.graph, transitions=(*self.graph.transitions, retry))

        self.assertEqual("use_entry_gate", graph.outgoing("enter_paid_hall", event_kind="retry")[0].target_node_id)


if __name__ == "__main__":
    unittest.main()
