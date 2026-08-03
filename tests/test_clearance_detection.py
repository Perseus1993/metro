from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from sandbox.metro_station_sandbox.runtime.clearance_detection import (
    build_clearance_debug,
)
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from metro_station_visualizer.mesa_export import (
    mesa_frames_to_visual_tracks,
)
from tests.test_evacuation_scenario import scenario_for_evacuation


class ClearanceDetectionTests(unittest.TestCase):
    def test_spawn_evidence_frame_captures_new_passenger_before_service(self) -> None:
        scenario = replace(
            scenario_for_evacuation(initial_persons=0, group_size=1, minutes=1),
            goal_graph_mode="active",
        )
        model = MetroStationModel(scenario, seed=317)
        passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

        model._capture_spawn_evidence_frame()

        self.assertIn(
            int(passenger.unique_id),
            {int(item["id"]) for item in model.frames[-1]["passengers"]},
        )

    def _completed_run(
        self,
        *,
        initial_persons: int = 12,
        group_size: int = 2,
    ) -> tuple[MetroStationModel, list[dict]]:
        scenario = replace(
            scenario_for_evacuation(
                initial_persons=initial_persons,
                group_size=group_size,
                minutes=3,
            ),
            goal_graph_mode="active",
        )
        model = MetroStationModel(scenario, seed=317)
        return model, model.run()

    def test_multi_passenger_clearance_has_per_passenger_trajectory_and_graph_evidence(
        self,
    ) -> None:
        model, frames = self._completed_run(initial_persons=20, group_size=2)

        runtime_debug = build_clearance_debug(model)
        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=model.scenario,
            facilities=model.facilities,
            service_events=model.facility_service_events,
            terminal_events=model.passenger_terminal_events,
            clearance_debug=runtime_debug,
        )
        graph_debug = payload["graph_debug"]

        self.assertTrue(payload["clearance_audit"]["cleared"])
        self.assertEqual("strict_goal_graph", payload["clearance_audit"]["evidence_mode"])
        self.assertEqual(20, graph_debug["counts"]["spawned_persons"])
        self.assertEqual(10, graph_debug["counts"]["passenger_groups"])
        self.assertEqual(10, len(graph_debug["passengers"]))
        self.assertTrue(all(graph_debug["checks"].values()))
        self.assertEqual([], graph_debug["blockers"])
        self.assertTrue(
            all(item["graph_complete"] for item in graph_debug["passengers"])
        )
        self.assertTrue(
            all(item["terminal_reached"] for item in graph_debug["passengers"])
        )
        self.assertTrue(
            all(
                item["trajectory"]["sample_count"] > 0
                for item in graph_debug["passengers"]
            )
        )

    def test_graph_complete_without_terminal_blocks_clearance(self) -> None:
        model, _frames = self._completed_run(initial_persons=2, group_size=1)
        missing_id = model.passenger_terminal_events.pop().passenger_id

        debug = build_clearance_debug(model)

        self.assertFalse(debug["cleared"])
        self.assertIn(missing_id, debug["missing_terminal_ids"])
        self.assertIn(missing_id, debug["graph_without_terminal_ids"])
        self.assertFalse(debug["checks"]["terminal_events_complete"])

    def test_terminal_with_incomplete_graph_blocks_clearance(self) -> None:
        model, _frames = self._completed_run(initial_persons=1, group_size=1)
        passenger_id = model.passenger_terminal_events[0].passenger_id
        runtime = model.passenger_goal_runtimes[passenger_id]
        runtime.state = replace(
            runtime.state,
            current_node_id=runtime.graph.entry_node_id,
            interaction_state=None,
            current_stage=None,
            commitment=None,
            queued_facility_id=None,
        )

        debug = build_clearance_debug(model)

        self.assertFalse(debug["cleared"])
        self.assertEqual([passenger_id], debug["incomplete_graph_ids"])
        self.assertFalse(debug["checks"]["goal_graphs_complete"])

    def test_duplicate_terminal_event_blocks_clearance(self) -> None:
        model, _frames = self._completed_run(initial_persons=1, group_size=1)
        duplicate = model.passenger_terminal_events[0]
        model.passenger_terminal_events.append(duplicate)

        debug = build_clearance_debug(model)

        self.assertFalse(debug["cleared"])
        self.assertEqual([duplicate.passenger_id], debug["duplicate_terminal_ids"])
        self.assertFalse(debug["checks"]["terminal_events_complete"])

    def test_missing_physical_trajectory_blocks_exported_clearance(self) -> None:
        model, frames = self._completed_run(initial_persons=2, group_size=1)
        missing_id = model.passenger_terminal_events[0].passenger_id
        stripped_frames = copy.deepcopy(frames)
        for frame in stripped_frames:
            frame["passengers"] = [
                passenger
                for passenger in frame["passengers"]
                if passenger["id"] != missing_id
            ]

        payload = mesa_frames_to_visual_tracks(
            frames=stripped_frames,
            scenario=model.scenario,
            facilities=model.facilities,
            service_events=model.facility_service_events,
            terminal_events=model.passenger_terminal_events,
            clearance_debug=build_clearance_debug(model),
        )

        self.assertFalse(payload["clearance_audit"]["cleared"])
        self.assertEqual([missing_id], payload["graph_debug"]["missing_trajectory_ids"])
        self.assertFalse(
            payload["graph_debug"]["checks"]["trajectory_evidence_complete"]
        )

    def test_single_sample_passenger_remains_in_exported_trajectory_ledger(self) -> None:
        model, frames = self._completed_run(initial_persons=2, group_size=1)
        passenger_id = model.passenger_terminal_events[0].passenger_id
        single_sample_frames = copy.deepcopy(frames)
        retained = False
        for frame in single_sample_frames:
            matching = [
                item for item in frame["passengers"] if item["id"] == passenger_id
            ]
            if matching and not retained:
                retained = True
                continue
            frame["passengers"] = [
                item for item in frame["passengers"] if item["id"] != passenger_id
            ]

        payload = mesa_frames_to_visual_tracks(
            frames=single_sample_frames,
            scenario=model.scenario,
            facilities=model.facilities,
            service_events=model.facility_service_events,
            terminal_events=model.passenger_terminal_events,
            clearance_debug=build_clearance_debug(model),
        )

        track = next(item for item in payload["agents"] if item["id"] == passenger_id)
        debug = next(
            item
            for item in payload["graph_debug"]["passengers"]
            if item["passenger_id"] == passenger_id
        )
        self.assertEqual(1, len(track["points"]))
        self.assertEqual(1, debug["trajectory"]["sample_count"])
        self.assertTrue(
            payload["graph_debug"]["checks"]["trajectory_evidence_complete"]
        )


if __name__ == "__main__":
    unittest.main()
