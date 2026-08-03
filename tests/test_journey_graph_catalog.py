from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sandbox.metro_station_sandbox.planning.journey_catalog import (
    JourneyGraphCatalog,
    default_journey_graph_catalog,
)
from sandbox.metro_station_sandbox.planning.journey_catalog_compiler import (
    compile_journey_graph_catalog,
)
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from sandbox.metro_station_sandbox.runtime.passenger_goal_runtime import PassengerGoalRuntime
from sandbox.metro_station_sandbox.design import create_design
from sandbox.metro_station_sandbox.station.graph import StationGraph


class JourneyGraphCatalogTests(unittest.TestCase):
    def test_default_catalog_covers_every_passenger_intent(self) -> None:
        catalog = default_journey_graph_catalog()
        for intent in AgentIntent:
            with self.subTest(intent=intent.value):
                self.assertIsNotNone(catalog.graph_for_intent(intent))

    def test_catalog_round_trip_is_stable(self) -> None:
        catalog = default_journey_graph_catalog()
        restored = JourneyGraphCatalog.from_mapping(catalog.as_dict())
        self.assertEqual(catalog.as_dict(), restored.as_dict())

    def test_catalog_compiler_adapts_transfer_graph_to_station_topology(self) -> None:
        station_graph = StationGraph.from_design(create_design("two_level_island_platform"))
        catalog = compile_journey_graph_catalog(station_graph)
        transfer = catalog.graph_for_intent(AgentIntent.TRANSFER)
        facility_stages = [node.facility_stage for node in transfer.nodes if node.facility_stage]
        self.assertEqual(["boarding_door"], facility_stages)

    def test_external_json_catalog_is_loaded_and_validated(self) -> None:
        payload = default_journey_graph_catalog().as_dict()
        payload["journeys"][AgentIntent.ENTER_AND_BOARD.value]["id"] = "configured_entry"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journeys.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            catalog = JourneyGraphCatalog.from_json_file(path)
        self.assertEqual(
            "configured_entry",
            catalog.graph_for_intent(AgentIntent.ENTER_AND_BOARD).graph_id,
        )

    def test_external_catalog_rejects_invalid_graph(self) -> None:
        payload = default_journey_graph_catalog().as_dict()
        payload["journeys"][AgentIntent.TRANSFER.value]["entry_node_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "entry node"):
            JourneyGraphCatalog.from_mapping(payload)

    def test_active_catalog_contract_rejects_missing_passenger_intent(self) -> None:
        complete = default_journey_graph_catalog()
        entry_graph = complete.graph_for_intent(AgentIntent.ENTER_AND_BOARD)
        partial = JourneyGraphCatalog(
            entries=((AgentIntent.ENTER_AND_BOARD.value, entry_graph),)
        )
        with self.assertRaisesRegex(ValueError, "missing required intents"):
            partial.require_intents(tuple(AgentIntent))

    def test_exit_and_transfer_graphs_complete_their_facility_chains(self) -> None:
        catalog = default_journey_graph_catalog()
        chains = {
            AgentIntent.EXIT_STATION: (
                ("vertical_transfer", "stairs:up"),
                ("exit_gate", "gate:exit"),
            ),
            AgentIntent.EVACUATE_STATION: (
                ("vertical_transfer", "stairs:up"),
                ("exit_gate", "gate:exit"),
            ),
            AgentIntent.TRANSFER: (
                ("vertical_transfer", "stairs:transfer"),
                ("boarding_door", "door:next_line"),
            ),
        }
        for intent, stages in chains.items():
            with self.subTest(intent=intent.value):
                runtime = PassengerGoalRuntime(catalog.graph_for_intent(intent))
                time_seconds = 0.0
                for stage, facility_id in stages:
                    for _ in range(len(runtime.graph.nodes)):
                        node = runtime.graph.node(runtime.state.current_node_id)
                        if node.kind == "wait_for_event":
                            time_seconds += 1.0
                            runtime.handle(
                                GoalEvent(
                                    kind=GoalEventKind.TRAIN_AVAILABLE.value,
                                    time_seconds=time_seconds,
                                )
                            )
                            continue
                        if node.kind == "enter_region":
                            time_seconds += 1.0
                            runtime.handle(
                                GoalEvent(
                                    kind=GoalEventKind.ENTERED_REGION.value,
                                    time_seconds=time_seconds,
                                    region_id=str(node.region_id),
                                )
                            )
                            continue
                        break
                    time_seconds += 1.0
                    node = runtime.graph.node(runtime.state.current_node_id)
                    runtime.handle(
                        GoalEvent(
                            kind=GoalEventKind.CANDIDATES_UPDATED.value,
                            time_seconds=time_seconds,
                            observation=DecisionObservation(
                                time_seconds=time_seconds,
                                current_region_id=node.decision_region_id,
                                entered_region_ids=(str(node.decision_region_id),),
                                candidates=(
                                    FacilityObservation(
                                        facility_id=facility_id,
                                        stage=stage,
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
                    for offset, kind in enumerate(
                        (
                            GoalEventKind.REACHED_QUEUE_CAPTURE,
                            GoalEventKind.QUEUE_JOINED,
                            GoalEventKind.SERVICE_STARTED,
                            GoalEventKind.SERVICE_COMPLETED,
                        ),
                        start=1,
                    ):
                        runtime.handle(
                            GoalEvent(
                                kind=kind.value,
                                time_seconds=time_seconds + offset,
                                facility_id=facility_id,
                            )
                        )
                    time_seconds += 4.0
                for _ in range(len(runtime.graph.nodes)):
                    node = runtime.graph.node(runtime.state.current_node_id)
                    if node.kind == "wait_for_event":
                        time_seconds += 1.0
                        runtime.handle(
                            GoalEvent(
                                kind=GoalEventKind.TRAIN_AVAILABLE.value,
                                time_seconds=time_seconds,
                            )
                        )
                        continue
                    if node.kind == "enter_region":
                        time_seconds += 1.0
                        runtime.handle(
                            GoalEvent(
                                kind=GoalEventKind.ENTERED_REGION.value,
                                time_seconds=time_seconds,
                                region_id=str(node.region_id),
                            )
                        )
                        continue
                    break
                self.assertEqual("complete", runtime.state.current_node_id)


if __name__ == "__main__":
    unittest.main()
