from __future__ import annotations

import unittest
from math import inf, nan, pi
from math import hypot
from random import Random
from dataclasses import replace
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

from shapely.geometry import LineString, Point

from sandbox.metro_station_sandbox.planning.plan import (
    AgentIntent,
    AgentState,
    CROWD_INTERACTION_STATES,
    FacilityStage,
    PASSIVE_STATES,
    RouteKey,
    WALKING_STATES,
)
from sandbox.metro_station_sandbox.agents import PassengerAgent
from sandbox.metro_station_sandbox.planning.behavior import (
    BehaviorActionKind,
    behavior_status_for_passenger,
)
from sandbox.metro_station_sandbox.design import (
    DesignConnection,
    DesignPort,
    StationDesignDocument,
    apply_react_flow_edges,
    create_design,
    to_react_flow,
    validate_design,
)
from metro_station_designer.server import (
    build_design_payload,
    compile_react_flow_payload,
    simulate_design_payload,
    simulation_job_payload,
    start_simulation_job,
    template_catalog_payload,
)
from sandbox.metro_station_sandbox.station.payload import geometry_payload
from sandbox.metro_station_sandbox.facilities.facility_queue import FacilityQueue
from sandbox.metro_station_sandbox.facilities.filters import (
    filter_boarding_doors_for_passenger,
    filter_platforms_for_passenger,
)
from sandbox.metro_station_sandbox.facilities.process import (
    FacilityKind,
    FacilitySpec,
    QueueCrossingGuard,
    QueueLayout,
)
from sandbox.metro_station_sandbox.facilities.runtime import (
    AmenityFacilityAgent,
    BoardingDoorProcessAgent,
    ElevatorProcessAgent,
    EscalatorProcessAgent,
    FacilityAgent,
    FacilityProcessAgent,
    GateProcessAgent,
    StairsProcessAgent,
)
from sandbox.metro_station_sandbox.facilities.service_events import FacilityServiceEvent
from sandbox.metro_station_sandbox.facilities.vertical import (
    ElevatorConfig,
    EscalatorConfig,
    EscalatorMode,
    VerticalFacilityConfig,
)
from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter
from sandbox.metro_station_sandbox.movement.backend import (
    BatchedJuPedSimMovementBackend,
    JuPedSimMovementBackend,
    MovementBackend,
    MovementResult,
)
from sandbox.metro_station_sandbox.planning.selection import pick_least_loaded, pick_logit
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from sandbox.metro_station_sandbox.runtime.demand_scheduler import DemandScheduler
from sandbox.metro_station_sandbox.runtime.snapshots import FacilitySnapshot, PassengerSnapshot
from sandbox.metro_station_sandbox.station.graph import StationGraph
from sandbox.metro_station_sandbox.station.layout_graph import LayoutGraph
from sandbox.metro_station_sandbox.station.geometry import (
    document_walkable_geometry,
    level_walkable_geometry,
)
from sandbox.metro_station_sandbox.station.scenario import GateSpec, StationGeometry, StationSandboxScenario
from metro_station_visualizer.geometry import load_station_geometry, meters
from metro_station_visualizer.layout import layout_payload
from metro_station_visualizer.field_routing import (
    QueueAttractivenessField,
    QueueFieldCandidate,
)
from metro_station_visualizer.floor_field import GridFloorField
from metro_station_visualizer.generate_jps_tracks import (
    ENTRY_GATE_PORTAL_RADIUS_M,
    POST_GATE_RADIUS_M,
    post_gate_portal_radius,
    queue_field_switching_is_enabled,
)
from metro_station_visualizer.tracks.vertical_choice import (
    VerticalChoiceOption,
    vertical_choice_probabilities,
)
from metro_station_visualizer.queue_runtime import (
    QUEUE_CAPTURE_APRONS_N,
    NativeQueueRuntime,
)
from metro_station_visualizer.mesa_export import mesa_frames_to_visual_tracks
from metro_station_visualizer.region_flow import (
    build_point_capture_flow,
    build_region_capture_flow,
)
from metro_station_visualizer.specs import FACILITY_QUEUES, GATE_QUEUE_SPECS
from metro_station_testkit.goal_journey_fixture import (
    compile_micro_facility_portal_binding,
)


class InstantMovementBackend(MovementBackend):
    def move(self, passenger: PassengerAgent) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


class LinearMovementBackend(MovementBackend):
    def __init__(self, *, step_units: float = 4.0) -> None:
        self.step_units = step_units
        self.move_count = 0

    def move(self, passenger: PassengerAgent) -> MovementResult:
        self.move_count += 1
        x, y = passenger.pos
        tx, ty = passenger.target
        distance = hypot(tx - x, ty - y)
        if distance <= 0.001 or distance <= self.step_units:
            return MovementResult(passenger.unique_id, passenger.target, reached=True)
        ratio = self.step_units / distance
        return MovementResult(
            passenger.unique_id,
            (
                x + (tx - x) * ratio,
                y + (ty - y) * ratio,
            ),
            reached=False,
        )


class RejectingPlacementBackend(LinearMovementBackend):
    def place_passenger(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        target: tuple[float, float] | None = None,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        raise RuntimeError("placement blocked")

    def resolve_placement(
        self,
        passenger: PassengerAgent,
        position: tuple[float, float],
        *,
        level_id: str | None = None,
    ) -> tuple[float, float]:
        raise RuntimeError("placement blocked")


def scenario_for(template_id: str, *, minutes: int = 1, admins: int = 0) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="unit_test",
        hour=18,
        minutes=minutes,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=1,
        exit_count_hour=1,
        source_label="unit",
        sample_hours=1,
        station_design=create_design(template_id),
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
        admin_agent_count=admins,
    )


def amenity_spec(*, stage: str = FacilityKind.AMENITY.value) -> FacilitySpec:
    return FacilitySpec(
        facility_id=f"amenity:{stage}",
        stage=stage,
        label="Water dispenser",
        kind=FacilityKind.AMENITY.value,
        direction="none",
        position=(2.0, 2.0),
        queue_layout=QueueLayout((2.0, 2.0), 1, (0.0, 0.0), (0.0, 0.0)),
        exit_position=(2.0, 2.0),
        service_persons_per_min=0,
        queue_state="idle",
        service_state="idle",
        release_route=(),
    )


class VisualExportPayloadTests(unittest.TestCase):
    def test_export_includes_scenario_and_train_context(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=2)
        frames = [
            {
                "time_seconds": 0.0,
                "passengers": [],
                "trains": [
                    {
                        "id": 1,
                        "line_id": "default",
                        "direction": "down",
                        "platform_id": "platform:default:down",
                        "state": "away",
                        "current_load_persons": 0,
                        "last_departed_load_persons": 0,
                        "departure_elapsed_seconds": None,
                        "departed_trains": 0,
                    }
                ],
                "metrics": {
                    "station_persons": 0,
                    "movement_backend": "UnitMovementBackend",
                    "jupedsim_operational_model": "collision_free_speed",
                },
            }
        ]

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
        )

        self.assertEqual("unit_test", payload["scenario"]["station_name"])
        self.assertEqual(18 * 3600, payload["scenario"]["clock_start_seconds"])
        self.assertEqual("UnitMovementBackend", payload["scenario"]["movement_backend"])
        self.assertEqual(0, payload["scenario"]["transfer_count_hour"])
        self.assertEqual(8, payload["scenario"]["elevator_min_dispatch_persons"])
        self.assertEqual(18.0, payload["scenario"]["elevator_max_dispatch_wait_seconds"])
        self.assertEqual(240, payload["train_service"]["headway_seconds"])
        self.assertEqual("away", payload["train_samples"][0]["trains"][0]["state"])
        self.assertIsNone(payload["evacuation_metrics"])

    def test_export_records_demand_window_and_clearance_limit(self) -> None:
        scenario = replace(scenario_for("visual_demo_station", minutes=5), demand_minutes=2)
        frames = [
            {
                "time_seconds": 180.0,
                "passengers": [],
                "trains": [],
                "metrics": {
                    "station_persons": 0,
                    "boarded_persons": 1,
                    "spawned_persons": 1,
                },
            }
        ]

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
        )
        audit = payload["clearance_audit"]

        self.assertEqual(120.0, audit["demand_duration_s"])
        self.assertEqual(300.0, audit["max_duration_s"])
        self.assertEqual(180.0, audit["final_time_s"])
        self.assertEqual(180.0, audit["clearance_time_s"])
        self.assertTrue(audit["cleared"])
        self.assertEqual(2, payload["scenario"]["demand_minutes"])
        self.assertEqual(3, payload["scenario"]["clearance_minutes"])

    def test_export_marks_horizon_limited_run_as_right_censored(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = [
            {
                "time_seconds": 60.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 10.0,
                        "y": 10.0,
                        "state": AgentState.QUEUEING_DOOR.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {"target": [10.0, 10.0]},
                        "current_level_id": "b2_platform",
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            }
        ]

        payload = mesa_frames_to_visual_tracks(frames=frames, scenario=scenario, facilities=[])

        self.assertFalse(payload["clearance_audit"]["cleared"])
        self.assertTrue(payload["clearance_audit"]["right_censored"])
        self.assertEqual("right_censored", payload["clearance_audit"]["outcome"])
        self.assertEqual(
            "b2_platform",
            payload["simulation_trace"]["snapshots"][0]["passengers"][0]["current_level_id"],
        )

    def test_passenger_snapshot_mapping_exposes_level_truth(self) -> None:
        snapshot = PassengerSnapshot.from_mapping(
            {
                "id": 7,
                "x": 1.0,
                "y": 2.0,
                "state": AgentState.WALKING_TO_PLATFORM.value,
                "intent": AgentIntent.ENTER_AND_BOARD.value,
                "current_level_id": "b2_platform",
            }
        )

        self.assertEqual("b2_platform", snapshot.current_level_id)
        self.assertEqual("b2_platform", snapshot.to_dict()["current_level_id"])

    def test_vertical_service_events_smooth_visual_tracks(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = [
            {
                "time_seconds": 0.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 10.0,
                        "y": 10.0,
                        "state": AgentState.RIDING_VERTICAL.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {"target": [10.0, 40.0]},
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
            {
                "time_seconds": 5.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 10.0,
                        "y": 10.0,
                        "state": AgentState.RIDING_VERTICAL.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {"target": [10.0, 40.0]},
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
            {
                "time_seconds": 10.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 10.0,
                        "y": 40.0,
                        "state": AgentState.WALKING_TO_PLATFORM.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {"target": [10.0, 40.0]},
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
        ]
        event = FacilityServiceEvent(
            event_id=1,
            facility_id="vertical:down_escalator_a:down:b1_concourse:b2_platform",
            facility_kind=FacilityKind.ESCALATOR.value,
            mode="down",
            passenger_ids=(1,),
            start_time=0.0,
            end_time=10.0,
            start_position=(10.0, 10.0),
            end_position=(10.0, 40.0),
        )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
            service_events=[event],
        )
        agent = payload["agents"][0]
        source_points = agent["points"]
        source_by_time = {point[0]: point for point in source_points}

        self.assertNotIn("presentation_points", agent)
        self.assertEqual(source_by_time[0.0][1:3], source_by_time[5.0][1:3])
        self.assertTrue(all(point[9]["visual_only"] is False for point in source_points))
        replay_fidelity = payload["simulation_trace"]["metadata"]["replay_fidelity"]
        self.assertEqual("points", replay_fidelity["visual_track_source_points_field"])
        self.assertEqual(
            "canonical_composite_points",
            replay_fidelity["presentation_position_source"],
        )
        self.assertFalse(replay_fidelity["facility_overlays_modify_source_points"])
        self.assertFalse(replay_fidelity["facility_overlays_control_passenger_bodies"])

    def test_gate_service_visual_tracks_queue_front_before_gate(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = [
            {
                "time_seconds": 0.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 17.588,
                        "y": 13.1029,
                        "state": AgentState.QUEUEING_GATE.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {
                            "kind": "queued",
                            "target": [17.588, 15.5029],
                            "facility_id": "entry_gate:gate_bank_a:lane_1",
                            "stage": FacilityStage.ENTRY_GATE.value,
                        },
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
            {
                "time_seconds": 5.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 17.0,
                        "y": 17.2,
                        "state": AgentState.WALKING_TO_VERTICAL.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {
                            "kind": "walk",
                            "target": [15.0, 20.0],
                            "facility_id": None,
                            "stage": None,
                        },
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
        ]
        event = FacilityServiceEvent(
            event_id=1,
            facility_id="entry_gate:gate_bank_a:lane_1",
            facility_kind=FacilityKind.GATE.value,
            mode=FacilityStage.ENTRY_GATE.value,
            passenger_ids=(1,),
            start_time=1.2,
            end_time=2.1,
            start_position=(17.588, 15.5029),
            end_position=(17.588, 15.66765),
            direction="in",
        )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
            service_events=[event],
        )
        source_points = payload["agents"][0]["points"]
        self.assertNotIn("presentation_points", payload["agents"][0])
        self.assertTrue(all(point[9]["visual_only"] is False for point in source_points))
        self.assertFalse(
            payload["simulation_trace"]["metadata"]["replay_fidelity"][
                "facility_overlays_control_passenger_bodies"
            ]
        )

    def test_gate_service_visual_uses_event_entry_when_queue_target_is_stale(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = [
            {
                "time_seconds": 0.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 17.588,
                        "y": 11.5029,
                        "state": AgentState.QUEUEING_GATE.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {
                            "kind": "queued",
                            "target": [17.588, 15.5029],
                            "facility_id": "entry_gate:gate_bank_a:lane_1",
                            "stage": FacilityStage.ENTRY_GATE.value,
                        },
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
            {
                "time_seconds": 5.0,
                "passengers": [
                    {
                        "id": 1,
                        "x": 17.0,
                        "y": 17.2,
                        "state": AgentState.WALKING_TO_VERTICAL.value,
                        "intent": AgentIntent.ENTER_AND_BOARD.value,
                        "goal": {"kind": "walk", "target": [15.0, 20.0]},
                    }
                ],
                "trains": [],
                "metrics": {"station_persons": 1, "spawned_persons": 1},
            },
        ]
        event = FacilityServiceEvent(
            event_id=1,
            facility_id="entry_gate:gate_bank_a:lane_1",
            facility_kind=FacilityKind.GATE.value,
            mode=FacilityStage.ENTRY_GATE.value,
            passenger_ids=(1,),
            start_time=1.2,
            end_time=2.1,
            start_position=(17.588, 13.9029),
            end_position=(17.588, 15.66765),
            direction="in",
        )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
            service_events=[event],
        )
        agent = payload["agents"][0]
        self.assertNotIn("presentation_points", agent)
        self.assertEqual(2, len(agent["points"]))
        self.assertTrue(all(not point[9]["visual_only"] for point in agent["points"]))

    def test_simultaneous_stairs_events_get_visual_lane_offsets(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = []
        for time_s in (0.0, 5.0, 10.0):
            frames.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": 1,
                            "x": 10.0,
                            "y": 10.0 if time_s < 10.0 else 40.0,
                            "state": AgentState.RIDING_VERTICAL.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [10.0, 40.0]},
                        },
                        {
                            "id": 2,
                            "x": 10.0,
                            "y": 10.0 if time_s < 10.0 else 40.0,
                            "state": AgentState.RIDING_VERTICAL.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [10.0, 40.0]},
                        },
                    ],
                    "trains": [],
                    "metrics": {"station_persons": 2, "spawned_persons": 2},
                }
            )
        events = [
            FacilityServiceEvent(
                event_id=1,
                facility_id="vertical:stairs_a:down:b1_concourse:b2_platform",
                facility_kind=FacilityKind.STAIRS.value,
                mode="down",
                passenger_ids=(1,),
                start_time=0.0,
                end_time=10.0,
                start_position=(10.0, 10.0),
                end_position=(10.0, 40.0),
            ),
            FacilityServiceEvent(
                event_id=2,
                facility_id="vertical:stairs_a:down:b1_concourse:b2_platform",
                facility_kind=FacilityKind.STAIRS.value,
                mode="down",
                passenger_ids=(2,),
                start_time=0.0,
                end_time=10.0,
                start_position=(10.0, 10.0),
                end_position=(10.0, 40.0),
            ),
        ]

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
            service_events=events,
        )
        self.assertTrue(all("presentation_points" not in agent for agent in payload["agents"]))
        self.assertEqual(2, len(payload["vertical_service_events"]))
        self.assertTrue(
            all(
                not point[9]["visual_only"]
                for agent in payload["agents"]
                for point in agent["points"]
            )
        )

    def test_elevator_batch_events_get_visual_car_offsets(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = []
        for time_s in (0.0, 5.0, 10.0):
            frames.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": 1,
                            "x": 10.0,
                            "y": 10.0 if time_s < 10.0 else 40.0,
                            "state": AgentState.RIDING_VERTICAL.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [10.0, 40.0]},
                        },
                        {
                            "id": 2,
                            "x": 10.0,
                            "y": 10.0 if time_s < 10.0 else 40.0,
                            "state": AgentState.RIDING_VERTICAL.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [10.0, 40.0]},
                        },
                    ],
                    "trains": [],
                    "metrics": {"station_persons": 2, "spawned_persons": 2},
                }
            )
        event = FacilityServiceEvent(
            event_id=1,
            facility_id="vertical:elevator_a:down:b1_concourse:b2_platform",
            facility_kind=FacilityKind.ELEVATOR.value,
            mode="batch",
            passenger_ids=(1, 2),
            start_time=0.0,
            board_end_time=0.0,
            arrive_time=10.0,
            end_time=10.0,
            start_position=(10.0, 10.0),
            end_position=(10.0, 40.0),
        )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
            service_events=[event],
        )
        self.assertTrue(all("presentation_points" not in agent for agent in payload["agents"]))
        self.assertEqual(1, len(payload["elevator_events"]))
        self.assertEqual([1, 2], payload["elevator_events"][0]["track_ids"])
        self.assertTrue(
            all(
                not point[9]["visual_only"]
                for agent in payload["agents"]
                for point in agent["points"]
            )
        )

    def test_stationary_visual_track_keeps_last_motion_heading(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = []
        for time_s, y in ((0.0, 10.0), (5.0, 20.0), (10.0, 20.0)):
            frames.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": 1,
                            "x": 10.0,
                            "y": y,
                            "state": AgentState.WALKING_TO_PLATFORM.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [10.0, 30.0]},
                        }
                    ],
                    "trains": [],
                    "metrics": {"station_persons": 1, "spawned_persons": 1},
                }
            )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
        )
        by_time = {point[0]: point for point in payload["agents"][0]["points"]}

        self.assertNotEqual(0.0, by_time[5.0][3])
        self.assertEqual(by_time[5.0][3], by_time[10.0][3])

    def test_visual_track_heading_uses_the_outgoing_edge_without_one_frame_lag(self) -> None:
        scenario = scenario_for("visual_demo_station", minutes=1)
        frames = []
        for time_s, x, y in (
            (0.0, 10.0, 10.0),
            (5.0, 10.0, 20.0),
            (10.0, 20.0, 20.0),
        ):
            frames.append(
                {
                    "time_seconds": time_s,
                    "passengers": [
                        {
                            "id": 1,
                            "x": x,
                            "y": y,
                            "state": AgentState.WALKING_TO_PLATFORM.value,
                            "intent": AgentIntent.ENTER_AND_BOARD.value,
                            "goal": {"target": [30.0, 20.0]},
                        }
                    ],
                    "trains": [],
                    "metrics": {"station_persons": 1, "spawned_persons": 1},
                }
            )

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=[],
        )
        by_time = {point[0]: point for point in payload["agents"][0]["points"]}

        self.assertAlmostEqual(pi / 2.0, by_time[0.0][3], places=3)
        self.assertAlmostEqual(0.0, by_time[5.0][3], places=3)
        self.assertAlmostEqual(0.0, by_time[10.0][3], places=3)


class StationGraphTests(unittest.TestCase):
    def test_templates_validate_and_compile_without_graph_fallbacks(self) -> None:
        for template_id in (
            "single_level_terminal",
            "two_level_island_platform",
            "three_level_transfer",
            "visual_demo_station",
        ):
            with self.subTest(template_id=template_id):
                document = create_design(template_id)
                issues = validate_design(document)
                self.assertEqual([], [issue.as_dict() for issue in issues])
                graph = StationGraph.from_design(document)
                self.assertGreater(len(graph.nodes), 0)
                self.assertGreater(len(graph.edges), 0)
                self.assertEqual([], [item.as_dict() for item in graph.compile_diagnostics])
                self.assertFalse(
                    any(edge.origin == "walkable_access_fallback" for edge in graph.edges)
                )

    def test_template_gate_ports_are_directional(self) -> None:
        document = create_design("single_level_terminal")
        gate = document.element_by_id()["gate_bank_a"]
        ports_by_id = {port.id: port for port in gate.ports}
        entrance_to_gate = next(
            connection
            for connection in document.connections
            if connection.id == "conn_entrance_to_gates"
        )
        gate_to_boarding = next(
            connection
            for connection in document.connections
            if connection.id == "conn_gate_to_boarding"
        )

        self.assertEqual("in", ports_by_id["service"].direction)
        self.assertEqual("out", ports_by_id["release"].direction)
        self.assertEqual("out", ports_by_id["unpaid"].direction)
        self.assertEqual("service", entrance_to_gate.target_port_id)
        self.assertFalse(entrance_to_gate.bidirectional)
        self.assertEqual("release", gate_to_boarding.source_port_id)
        self.assertFalse(gate_to_boarding.bidirectional)

    def test_validation_reports_missing_explicit_connection(self) -> None:
        document = create_design("single_level_terminal")
        broken = replace(
            document,
            connections=tuple(
                connection
                for connection in document.connections
                if connection.id != "conn_gate_to_boarding"
            ),
        )
        issue_codes = {issue.code for issue in validate_design(broken)}
        self.assertIn("graph.enter_path_missing", issue_codes)

    def test_route_uses_current_level_for_overlapping_vertical_nodes(self) -> None:
        graph = StationGraph.from_design(create_design("three_level_transfer"))
        current_position = graph.nodes["vertical:down_escalator_a:b2_transfer"].position
        nearest_on_level = graph.nearest_node(
            current_position,
            graph.nodes_matching(level_id="b2_transfer"),
        )
        self.assertEqual("vertical:down_escalator_a:b2_transfer", nearest_on_level.node_id)
        route = graph.route_from_position_to(
            current_position,
            kind="facility_entry",
            facility_stage="vertical_transfer",
            direction="down",
            start_level_id="b2_transfer",
        )
        self.assertTrue(route)

    def test_vertical_direction_can_fall_back_to_chinese_labels(self) -> None:
        document = create_design("two_level_island_platform")
        document = replace(
            document,
            elements=tuple(
                replace(element, label="下行扶梯 A", direction=None, metadata={})
                if element.id == "down_escalator_a"
                else replace(element, label="上行扶梯 A", direction=None, metadata={})
                if element.id == "up_escalator_a"
                else element
                for element in document.elements
            ),
        )
        graph = StationGraph.from_design(document)

        self.assertEqual(
            "down",
            graph.nodes["vertical:down_escalator_a:b1_concourse"].direction,
        )
        self.assertEqual(
            "up",
            graph.nodes["vertical:up_escalator_a:b1_concourse"].direction,
        )

    def test_design_ports_round_trip_and_project_to_react_flow_handles(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort(
                        "public_exit",
                        "walk",
                        level_id="l1_terminal",
                        position_m=(6.0, 22.5),
                    ),
                ),
            )
            if element.id == "entrance_a"
            else replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort(
                        "hall_entry",
                        "walk",
                        level_id="l1_terminal",
                        position_m=(10.0, 22.5),
                    ),
                ),
            )
            if element.id == "main_hall"
            else element
            for element in document.elements
        )
        connections = tuple(
            replace(
                connection,
                source_port_id="public_exit",
                target_port_id="hall_entry",
            )
            if connection.id == "conn_entrance_to_hall"
            else connection
            for connection in document.connections
        )
        document = replace(document, elements=elements, connections=connections)

        self.assertEqual([], [issue.as_dict() for issue in validate_design(document)])

        round_tripped = StationDesignDocument.from_dict(document.as_dict())
        self.assertTrue(
            any(port.id == "public_exit" for port in round_tripped.elements[1].ports)
        )
        flow = to_react_flow(round_tripped)
        edge = next(edge for edge in flow["edges"] if edge["id"] == "edge:conn_entrance_to_hall")

        self.assertEqual("public_exit", edge["sourceHandle"])
        self.assertEqual("hall_entry", edge["targetHandle"])

        applied = apply_react_flow_edges(round_tripped, flow["edges"])
        applied_connection = next(
            connection
            for connection in applied.connections
            if connection.id == "conn_entrance_to_hall"
        )
        self.assertEqual("public_exit", applied_connection.source_port_id)
        self.assertEqual("hall_entry", applied_connection.target_port_id)

    def test_design_inspector_reports_clean_template_compile(self) -> None:
        catalog = template_catalog_payload()
        self.assertIn("xyflow / React Flow", [item["name"] for item in catalog["reference_wheels"]])
        self.assertIn("equipment", [item["id"] for item in catalog["component_palette"]])
        self.assertIn("stairs", [item["id"] for item in catalog["component_palette"]])
        operation_field_ids = {
            field["id"]
            for group in catalog["operations_schema"]
            for field in group["fields"]
        }
        self.assertIn("entry_count_hour", operation_field_ids)
        self.assertIn("transfer_count_hour", operation_field_ids)
        self.assertIn("elevator_cycle_seconds", operation_field_ids)
        self.assertIn("elevator_min_dispatch_persons", operation_field_ids)
        self.assertIn("elevator_max_dispatch_wait_seconds", operation_field_ids)

        payload = build_design_payload("single_level_terminal")
        self.assertEqual("ok", payload["summary"]["status"])
        self.assertEqual(8683, payload["operations"]["entry_count_hour"])
        self.assertEqual(0, payload["summary"]["fallback_edges"])
        self.assertGreater(len(payload["react_flow"]["nodes"]), 0)
        self.assertTrue(
            any(node.get("data", {}).get("ports") for node in payload["react_flow"]["nodes"])
        )

    def test_design_inspector_compile_normalizes_operations(self) -> None:
        draft = compile_react_flow_payload(
            {
                "template_id": "single_level_terminal",
                "operations": {
                    "entry_count_hour": "1234",
                    "transfer_count_hour": "567",
                    "gate_service_persons_per_min": "-7",
                    "elevator_min_dispatch_persons": "9",
                    "elevator_max_dispatch_wait_seconds": "22.5",
                    "elevator_cycle_seconds": "18.5",
                    "train_headway_seconds": "9999",
                },
            }
        )

        self.assertEqual(1234, draft["operations"]["entry_count_hour"])
        self.assertEqual(567, draft["operations"]["transfer_count_hour"])
        self.assertEqual(1, draft["operations"]["gate_service_persons_per_min"])
        self.assertEqual(9, draft["operations"]["elevator_min_dispatch_persons"])
        self.assertEqual(22.5, draft["operations"]["elevator_max_dispatch_wait_seconds"])
        self.assertEqual(18.5, draft["operations"]["elevator_cycle_seconds"])
        self.assertEqual(1800, draft["operations"]["train_headway_seconds"])

    def test_design_inspector_simulate_returns_trajectory_summary(self) -> None:
        result = simulate_design_payload(
            {
                "template_id": "single_level_terminal",
                "entry_count_hour": 60,
                "exit_count_hour": 0,
                "minutes": 1,
                "seed": 42,
            }
        )

        self.assertEqual("ok", result["status"], result.get("error"))
        self.assertIn("completion_rate", result["metrics"])
        self.assertIn(result["trajectory_report"]["pass_fail"], {"pass", "warn", "fail"})

    def test_design_inspector_simulation_job_reports_progress(self) -> None:
        job = start_simulation_job(
            {
                "template_id": "single_level_terminal",
                "entry_count_hour": 30,
                "exit_count_hour": 0,
                "minutes": 1,
                "tick_seconds": 10,
                "seed": 42,
            }
        )
        self.assertIn(job["status"], {"queued", "running"})
        self.assertEqual(0, job["step"])

        deadline = monotonic() + 15.0
        state = job
        while monotonic() < deadline:
            latest = simulation_job_payload(job["job_id"])
            self.assertIsNotNone(latest)
            state = latest
            if state["status"] in {"done", "error"}:
                break
            sleep(0.05)

        self.assertEqual("done", state["status"], state.get("error"))
        self.assertEqual(state["total_steps"], state["step"])
        self.assertGreater(state["total_steps"], 0)
        self.assertEqual("ok", state["result"]["status"])

    def test_design_inspector_compile_accepts_dropped_component_node(self) -> None:
        payload = build_design_payload("single_level_terminal")
        level_node = next(
            node for node in payload["react_flow"]["nodes"] if node["id"].startswith("level:")
        )
        draft_node = {
            "id": "element:draft_equipment_test",
            "type": "facilityNode",
            "parentId": level_node["id"],
            "position": {"x": 42.0, "y": 16.0},
            "width": 4.0,
            "height": 3.0,
            "style": {"width": 4.0, "height": 3.0},
            "data": {
                "inspector_created": True,
                "palette_id": "equipment",
                "kind": "equipment",
                "level_id": level_node["data"]["level_id"],
                "role": "facility",
                "label": "Equipment",
                "geometry": {
                    "shape": "rect",
                    "x_m": 42.0,
                    "y_m": 16.0,
                    "width_m": 4.0,
                    "height_m": 3.0,
                    "rotation_deg": 0.0,
                    "points_m": [],
                },
                "metadata": {"inspector_created": True},
            },
        }

        draft = compile_react_flow_payload(
            {
                "template_id": "single_level_terminal",
                "nodes": [*payload["react_flow"]["nodes"], draft_node],
                "edges": payload["react_flow"]["edges"],
            }
        )
        elements_by_id = {
            element["id"]: element for element in draft["document"]["elements"]
        }

        self.assertIn("draft_equipment_test", elements_by_id)
        self.assertEqual("equipment", elements_by_id["draft_equipment_test"]["kind"])
        self.assertEqual(
            {"x_m": 42.0, "y_m": 16.0, "width_m": 4.0, "height_m": 3.0},
            {
                key: elements_by_id["draft_equipment_test"]["geometry"][key]
                for key in ("x_m", "y_m", "width_m", "height_m")
            },
        )

    def test_design_inspector_compile_accepts_dropped_vertical_connector(self) -> None:
        payload = build_design_payload("two_level_island_platform")
        level_node = next(
            node
            for node in payload["react_flow"]["nodes"]
            if node["id"] == "level:b1_concourse"
        )
        draft_node = {
            "id": "element:draft_stairs_test",
            "type": "verticalConnector",
            "parentId": level_node["id"],
            "position": {"x": 58.0, "y": 28.0},
            "width": 8.0,
            "height": 12.0,
            "style": {"width": 8.0, "height": 12.0},
            "data": {
                "inspector_created": True,
                "palette_id": "stairs",
                "kind": "stairs",
                "level_id": "b1_concourse",
                "role": "vertical_connector",
                "label": "Stairs",
                "connects_levels": ["b1_concourse", "b2_platform"],
                "direction": "both",
                "capacity": 120,
                "geometry": {
                    "shape": "rect",
                    "x_m": 58.0,
                    "y_m": 28.0,
                    "width_m": 8.0,
                    "height_m": 12.0,
                    "rotation_deg": 0.0,
                    "points_m": [],
                },
                "metadata": {"inspector_created": True},
            },
        }

        draft = compile_react_flow_payload(
            {
                "template_id": "two_level_island_platform",
                "nodes": [*payload["react_flow"]["nodes"], draft_node],
                "edges": payload["react_flow"]["edges"],
            }
        )
        elements_by_id = {
            element["id"]: element for element in draft["document"]["elements"]
        }
        ports_by_id = {
            port["id"]: port for port in elements_by_id["draft_stairs_test"]["ports"]
        }

        self.assertEqual("vertical_connector", elements_by_id["draft_stairs_test"]["role"])
        self.assertEqual(
            ["b1_concourse", "b2_platform"],
            elements_by_id["draft_stairs_test"]["connects_levels"],
        )
        self.assertIn("level:b1_concourse", ports_by_id)
        self.assertIn("level:b2_platform", ports_by_id)

    def test_design_inspector_compile_exposes_broken_edge_state(self) -> None:
        payload = build_design_payload("single_level_terminal")
        draft = compile_react_flow_payload(
            {
                "template_id": "single_level_terminal",
                "nodes": payload["react_flow"]["nodes"],
                "edges": [],
            }
        )
        issue_codes = {issue["code"] for issue in draft["validation_issues"]}

        self.assertEqual("error", draft["summary"]["status"])
        self.assertIn("graph.enter_path_missing", issue_codes)
        self.assertEqual(0, draft["summary"]["fallback_edges"])

    def test_graph_marks_legacy_endpoint_inference_and_walkable_fallback(self) -> None:
        document = create_design("single_level_terminal")
        legacy_document = replace(
            document,
            elements=tuple(replace(element, ports=()) for element in document.elements),
            connections=tuple(
                replace(connection, source_port_id=None, target_port_id=None)
                for connection in document.connections
                if not connection.id.startswith("conn_access_")
            ),
        )
        graph = StationGraph.from_design(
            legacy_document,
            include_walkable_access_edges=True,
        )
        diagnostic_codes = {diagnostic.code for diagnostic in graph.compile_diagnostics}
        fallback_edges = [
            edge for edge in graph.edges if edge.origin == "walkable_access_fallback"
        ]

        self.assertIn("graph.connection_endpoint_inferred", diagnostic_codes)
        self.assertIn("graph.same_level_access_fallback", diagnostic_codes)
        self.assertTrue(fallback_edges)
        self.assertTrue(
            all(
                edge.detail_id is not None
                for edge in graph.edges
                if edge.origin == "design_connection"
            )
        )

    def test_graph_uses_explicit_port_refs_without_endpoint_inference(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort("public_exit", "walk", level_id="l1_terminal"),
                ),
            )
            if element.id == "entrance_a"
            else replace(
                element,
                ports=(
                    *element.ports,
                    DesignPort("hall_entry", "walk", level_id="l1_terminal"),
                ),
            )
            if element.id == "main_hall"
            else element
            for element in document.elements
        )
        connections = tuple(
            replace(
                connection,
                source_port_id="public_exit",
                target_port_id="hall_entry",
            )
            if connection.id == "conn_entrance_to_hall"
            else connection
            for connection in document.connections
        )
        graph = StationGraph.from_design(
            replace(document, elements=elements, connections=connections)
        )
        connection_diagnostics = [
            diagnostic
            for diagnostic in graph.compile_diagnostics
            if diagnostic.connection_id == "conn_entrance_to_hall"
        ]
        connection_edges = [
            edge for edge in graph.edges if edge.detail_id == "conn_entrance_to_hall"
        ]

        self.assertNotIn(
            "graph.connection_endpoint_inferred",
            {diagnostic.code for diagnostic in connection_diagnostics},
        )
        self.assertTrue(connection_edges)
        self.assertTrue(all(edge.origin == "design_connection" for edge in connection_edges))

    def test_validation_reports_invalid_design_port_references(self) -> None:
        document = create_design("single_level_terminal")
        elements = tuple(
            replace(
                element,
                ports=(
                    DesignPort(
                        "entry_only",
                        "walk",
                        direction="in",
                        level_id="l1_terminal",
                    ),
                ),
            )
            if element.id == "entrance_a"
            else element
            for element in document.elements
        )
        connections = (
            DesignConnection(
                "conn_bad_port",
                "entrance_a",
                "main_hall",
                "walk",
                bidirectional=False,
                source_port_id="entry_only",
                target_port_id="missing",
            ),
        )
        document = replace(document, elements=elements, connections=connections)
        issue_codes = {issue.code for issue in validate_design(document)}

        self.assertIn("connections.source_port_not_output", issue_codes)
        self.assertIn("connections.unknown_target_port", issue_codes)


class PassengerFlowTests(unittest.TestCase):
    def test_scenario_rejects_invalid_runtime_divisors(self) -> None:
        base_kwargs = {
            "station_name": "invalid",
            "hour": 18,
            "minutes": 1,
            "tick_seconds": 5,
            "group_size": 1,
            "entry_count_hour": 1,
            "exit_count_hour": 0,
            "source_label": "unit",
            "sample_hours": 1,
            "station_design": create_design("single_level_terminal"),
        }

        for field, value in {
            "tick_seconds": 0,
            "group_size": 0,
            "crowd_radius_units": 0.0,
            "walk_units_per_tick": inf,
            "boarding_speed_multiplier": 0.0,
            "jupedsim_target_radius_units": nan,
            "gate_lane_edge_inset_max": -0.1,
            "demand_minutes": 2,
        }.items():
            with self.subTest(field=field):
                kwargs = {**base_kwargs, field: value}
                with self.assertRaisesRegex(ValueError, field):
                    StationSandboxScenario(**kwargs)

    def test_facility_release_policy_defaults_and_overrides_are_spec_driven(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=7,
            movement_backend=InstantMovementBackend(),
        )
        gate = model.gates[0]

        self.assertEqual(
            [0, -1, 1, 0, -1, 1],
            [gate._release_column_order(index) for index in range(6)],
        )
        self.assertEqual([4, 5, 3, 6, 7, 8, 9], gate._release_forward_steps(4))

        gate.spec = replace(
            gate.spec,
            release_column_count=5,
            release_spacing_min=0.9,
            release_spacing_max=1.4,
            release_clearance_pad=0.0,
            release_personal_factor=1.5,
            release_lateral_range=1,
            release_forward_extra=2,
        )

        self.assertEqual(
            [0, -1, 1, -2, 2, 0],
            [gate._release_column_order(index) for index in range(6)],
        )
        self.assertAlmostEqual(1.2, gate._release_spacing())
        self.assertEqual(
            [
                (4.0, 0.0),
                (4.0, -1.0),
                (4.0, 1.0),
                (5.0, 0.0),
                (5.0, -1.0),
                (5.0, 1.0),
                (3.0, 0.0),
                (3.0, -1.0),
                (3.0, 1.0),
                (6.0, 0.0),
                (6.0, -1.0),
                (6.0, 1.0),
            ],
            gate._release_candidates(
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
                1.0,
                0,
                4,
            ),
        )

    def test_gate_lane_edge_inset_is_scenario_driven(self) -> None:
        default_model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=3,
            movement_backend=InstantMovementBackend(),
        )
        reduced_inset_model = MetroStationModel(
            replace(
                scenario_for("visual_demo_station"),
                gate_lane_edge_inset_max=0.1,
            ),
            seed=3,
            movement_backend=InstantMovementBackend(),
        )
        default_positions = [
            gate.spec.position
            for gate in default_model.gates
            if "lane_" in gate.facility_id
        ]
        reduced_inset_positions = [
            gate.spec.position
            for gate in reduced_inset_model.gates
            if "lane_" in gate.facility_id
        ]

        self.assertEqual(len(default_positions), len(reduced_inset_positions))
        self.assertGreater(len(default_positions), 1)
        axis = 0 if (
            max(x for x, _ in default_positions) - min(x for x, _ in default_positions)
        ) >= (
            max(y for _, y in default_positions) - min(y for _, y in default_positions)
        ) else 1
        self.assertLess(
            min(position[axis] for position in reduced_inset_positions),
            min(position[axis] for position in default_positions),
        )
        self.assertGreater(
            max(position[axis] for position in reduced_inset_positions),
            max(position[axis] for position in default_positions),
        )
        self.assertTrue(
            all(gate.spec.fallback_queue_spacing == 0.8 for gate in default_model.gates)
        )
        self.assertTrue(
            all(gate.spec.fallback_queue_capacity == 8 for gate in default_model.gates)
        )
        with self.assertRaisesRegex(ValueError, "portals.clearance_too_small"):
            MetroStationModel(
                replace(
                    scenario_for("visual_demo_station"),
                    gate_lane_edge_inset_max=0.0,
                ),
                seed=3,
                movement_backend=InstantMovementBackend(),
            )

    def test_gate_queue_crossing_guard_is_layout_spec_driven(self) -> None:
        design_model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=5,
            movement_backend=InstantMovementBackend(),
        )
        scenario_graph = LayoutGraph.from_scenario(
            replace(scenario_for("visual_demo_station"), station_design=None)
        )
        scenario_entry_gate = next(
            facility for facility in scenario_graph.facilities if facility.facility_id == "entry_gate:0"
        )
        scenario_exit_gate = next(
            facility for facility in scenario_graph.facilities if facility.facility_id == "exit_gate:0"
        )

        self.assertTrue(all(gate.spec.queue_crossing_guard.enabled for gate in design_model.gates))
        self.assertFalse(
            any(gate.spec.queue_crossing_guard.enabled for gate in design_model.exit_gates)
        )
        self.assertGreater(design_model.gates[0].spec.queue_crossing_guard.tolerance_units, 0.0)
        self.assertGreater(design_model.gates[0].spec.queue_crossing_guard.lane_half_width_units, 0.0)
        self.assertTrue(scenario_entry_gate.queue_crossing_guard.enabled)
        self.assertFalse(scenario_exit_gate.queue_crossing_guard.enabled)

    def test_scenario_layout_uses_geometry_level_ids(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station"),
            station_design=None,
            geometry=replace(
                StationGeometry(),
                concourse_level_id="L1",
                platform_level_id="L2",
            ),
        )

        graph = LayoutGraph.from_scenario(scenario)

        self.assertEqual(
            {"L1"},
            {facility.entry_level_id for facility in graph.facilities if facility.kind == "gate"},
        )
        self.assertEqual("L1", graph.nodes["unpaid_hall"].level)
        self.assertEqual("L1", graph.nodes["vertical_decision"].level)
        self.assertEqual("L2", graph.nodes["platform_hub"].level)
        self.assertEqual("L2", graph.nodes["platform_entry"].level)
        boarding_door = next(
            facility for facility in graph.facilities if facility.stage == FacilityStage.BOARDING_DOOR.value
        )
        self.assertEqual("L2", boarding_door.entry_level_id)

    def test_passenger_fallback_initial_level_uses_geometry_level_ids(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station"),
            station_design=None,
            geometry=replace(
                StationGeometry(),
                concourse_level_id="L1",
                platform_level_id="L2",
            ),
        )
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=4,
            movement_backend=InstantMovementBackend(),
        )
        model.layout_graph = LayoutGraph.from_scenario(scenario)

        # This unit isolates legacy initial-position fallback.  The model was
        # deliberately compiled from a different design, so starting its Goal
        # Graph against the swapped layout would create an invalid hybrid.
        with patch.object(model.goal_coordinator, "initialize"):
            entry_passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            exit_passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
            )

        self.assertEqual("L1", entry_passenger.current_level_id)
        self.assertEqual("L2", exit_passenger.current_level_id)

    def test_default_scenario_queue_steps_match_legacy_axis_values(self) -> None:
        graph = LayoutGraph.from_scenario(
            replace(scenario_for("visual_demo_station"), station_design=None)
        )
        entry_gate = next(
            facility for facility in graph.facilities if facility.facility_id == "entry_gate:0"
        )
        exit_gate = next(
            facility for facility in graph.facilities if facility.facility_id == "exit_gate:0"
        )
        vertical = next(
            facility for facility in graph.facilities if facility.facility_id == "vertical:0"
        )

        self.assertEqual((-0.72, 0.0), entry_gate.queue_layout.col_step)
        self.assertEqual((0.0, 1.0), entry_gate.queue_layout.row_step)
        self.assertEqual((0.72, 0.0), exit_gate.queue_layout.col_step)
        self.assertEqual((0.0, 1.0), exit_gate.queue_layout.row_step)
        self.assertEqual((-0.72, 0.0), vertical.queue_layout.col_step)
        self.assertEqual((0.0, 0.9), vertical.queue_layout.row_step)

    def test_diagonal_gate_queue_steps_follow_gate_geometry(self) -> None:
        geometry = replace(
            StationGeometry(),
            queue_spacing=1.0,
            gates=(GateSpec("D", (10.0, 10.0), (8.0, 8.0), (12.0, 12.0)),),
            exit_gates=(),
            vertical_transports=(),
            boarding_doors=(),
        )
        graph = LayoutGraph.from_scenario(
            replace(
                scenario_for("visual_demo_station"),
                station_design=None,
                geometry=geometry,
            )
        )
        gate = graph.facilities[0]
        col_step = gate.queue_layout.col_step
        row_step = gate.queue_layout.row_step

        self.assertAlmostEqual(1.0, hypot(*col_step), places=6)
        self.assertAlmostEqual(1.0, hypot(*row_step), places=6)
        self.assertAlmostEqual(0.0, col_step[0] * row_step[0] + col_step[1] * row_step[1], places=6)
        self.assertLess(col_step[0], 0.0)
        self.assertLess(col_step[1], 0.0)
        self.assertGreater(row_step[1], 0.0)

    def test_gate_pass_completes_only_after_physical_traversal(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=8,
            movement_backend=InstantMovementBackend(),
        )
        gate = model.gates[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)

        gate._start_service(passenger, None, release_index=0, release_count=1)

        self.assertTrue(passenger.passive_facility_service)
        self.assertFalse(passenger.movement_suppressed_this_step())
        self.assertEqual(0, gate.served_persons)
        self.assertEqual(1, len(gate.active_passes))
        event = model.facility_service_events[0]
        total_steps = gate.active_passes[0].total_steps
        for _ in range(total_steps):
            gate._advance_active_passes()

        self.assertFalse(passenger.passive_facility_service)
        self.assertTrue(passenger.movement_suppressed_this_step())
        self.assertEqual(event.end_position, passenger.pos)
        self.assertLessEqual(
            hypot(
                event.end_position[0] - event.start_position[0],
                event.end_position[1] - event.start_position[1],
            ),
            model.scenario.jupedsim_desired_speed_mps
            * max(0.0, event.end_time - event.start_time)
            + 0.001,
        )
        self.assertEqual(1, gate.served_persons)

    def test_agent_plan_contains_no_strategic_facility_actions(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=37,
            movement_backend=InstantMovementBackend(),
        )
        for intent in AgentIntent:
            with self.subTest(intent=intent.value):
                plan = model.plan_for_intent(intent)
                self.assertFalse(hasattr(plan, "action_sequence"))
                self.assertFalse(hasattr(plan, "chosen_facilities"))

    def test_model_reports_missing_required_entry_gates(self) -> None:
        scenario = scenario_for("single_level_terminal")
        compiled_without_facilities = SimpleNamespace(
            facilities=(),
            facility_portal_bindings=(),
        )

        with patch(
            "sandbox.metro_station_sandbox.runtime.mesa_model.DesignCompiler.compile",
            return_value=compiled_without_facilities,
        ):
            with self.assertRaisesRegex(ValueError, "entry gate facility"):
                MetroStationModel(scenario, movement_backend=InstantMovementBackend())

    def test_model_exposes_no_facility_choice_or_preselection_api(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            movement_backend=InstantMovementBackend(),
        )

        self.assertFalse(hasattr(model, "request_facility_choice"))
        self.assertFalse(hasattr(model, "preselect_facility_choice"))
        self.assertFalse(hasattr(model, "join_preselected_facility_queue"))

    def test_after_vertical_route_failure_does_not_fall_back_to_zone(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station"),
            audit_enabled=True,
            audit_print_events=False,
        )
        model = MetroStationModel(
            scenario,
            seed=35,
            movement_backend=InstantMovementBackend(),
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        wrong_up_transfer = next(
            transport
            for transport in model.vertical_transports
            if transport.spec.direction == "up"
            and transport.spec.kind == FacilityKind.STAIRS.value
        )
        passenger.pos = wrong_up_transfer.spec.exit_position
        passenger.current_level_id = wrong_up_transfer.spec.exit_level_id
        passenger.assigned_line_id = "default"
        passenger.assigned_direction = "down"

        route = model.route_for_key(RouteKey.AFTER_VERTICAL, passenger)

        self.assertEqual((), route)
        self.assertEqual(1, model.audit.counts["route_planning_failed"])
        self.assertEqual(
            f"route_planning_failed:{RouteKey.AFTER_VERTICAL.value}",
            passenger.last_replan_reason,
        )

    def test_complete_departure_removes_platform_waiting_reference(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            movement_backend=InstantMovementBackend(),
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.TRANSFER,
        )
        model.passengers.append(passenger)
        model.platform.join_waiting(passenger)

        model.complete_departure(passenger, boarded=False, goal_authorized=True)

        self.assertNotIn(passenger, model.platform.waiting)
        self.assertFalse(any(passenger in door.queue for door in model.boarding_doors))

    def test_elevator_finalize_preserves_in_progress_cabin(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            movement_backend=InstantMovementBackend(),
        )
        elevator = next(
            facility
            for facility in model.vertical_transports
            if isinstance(facility, ElevatorProcessAgent)
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        elevator.cabin_passengers = [passenger]
        elevator.cabin_load_persons = 1
        elevator.cabin_state = "moving"
        elevator._begin_passive_vertical_service(passenger)
        position_before_finalize = passenger.pos

        elevator.finalize()

        self.assertTrue(passenger.passive_facility_service)
        self.assertEqual([passenger], elevator.cabin_passengers)
        self.assertEqual(1, elevator.cabin_load_persons)
        self.assertEqual("moving", elevator.cabin_state)
        self.assertEqual(position_before_finalize, passenger.pos)

    def test_jupedsim_backend_preserves_strict_parameter(self) -> None:
        backend = JuPedSimMovementBackend(JuPedSimAdapter(), strict=False)

        self.assertFalse(backend.strict)

    def test_visual_demo_initial_positions_stay_on_intent_level(self) -> None:
        scenario = scenario_for("visual_demo_station")
        model = MetroStationModel(
            scenario,
            seed=13,
            movement_backend=InstantMovementBackend(),
        )
        document = scenario.station_design
        self.assertIsNotNone(document)
        assert document is not None
        walkable = document_walkable_geometry(document)
        b1_domain = level_walkable_geometry(document, "b1_concourse", walkable)
        b2_domain = level_walkable_geometry(document, "b2_platform", walkable)
        b2_platform_y = document.constraints.canvas_height_m * 0.60

        entry_passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(8)
        ]
        exit_passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
            )
            for _ in range(8)
        ]

        self.assertTrue(all(item.current_level_id == "b1_concourse" for item in entry_passengers))
        self.assertTrue(all(b1_domain.covers(Point(item.pos)) for item in entry_passengers))
        self.assertTrue(all(item.current_level_id == "b2_platform" for item in exit_passengers))
        self.assertTrue(all(b2_domain.covers(Point(item.pos)) for item in exit_passengers))
        self.assertTrue(all(item.pos[1] >= b2_platform_y for item in exit_passengers))

    def test_jupedsim_walkable_area_can_be_scoped_to_level(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=14,
            movement_backend=InstantMovementBackend(),
        )

        platform_point = Point(meters((0.251, 0.785)))

        self.assertTrue(model.jupedsim_walkable_area().covers(platform_point))
        self.assertFalse(model.jupedsim_walkable_area("b1_concourse").covers(platform_point))
        self.assertTrue(model.jupedsim_walkable_area("b2_platform").covers(platform_point))

    def test_behavior_status_describes_region_goal_and_queue_mode(self) -> None:
        model = MetroStationModel(scenario_for("single_level_terminal"), seed=11)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )

        initial = behavior_status_for_passenger(passenger)
        self.assertEqual(BehaviorActionKind.WALK_TO_REGION.value, initial.action)
        self.assertEqual("station_entrance", initial.region_goal.origin_region)
        self.assertEqual("train_interior", initial.region_goal.destination_region)

        model.gates[0].join_queue(passenger, authority="goal_graph")
        queued = behavior_status_for_passenger(passenger)
        self.assertEqual(BehaviorActionKind.WAIT_IN_QUEUE.value, queued.action)
        self.assertEqual("enqueued", queued.queue_mode)
        self.assertEqual("entry_gate", queued.facility_stage)

    def test_entry_passenger_walks_to_decision_region_before_committing(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=28,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        self.assertEqual(AgentState.ENTERING_STATION.value, passenger.state)
        self.assertEqual("goal_region", passenger.current_goal.kind)
        self.assertIsNone(passenger.goal_runtime.state.commitment)
        decision_target = passenger.target
        self.assertGreater(
            hypot(
                passenger.pos[0] - decision_target[0],
                passenger.pos[1] - decision_target[1],
            ),
            model.scenario.jupedsim_target_radius_units,
        )

        passenger.pos = decision_target
        passenger.advance_after_movement(True)

        commitment = passenger.goal_runtime.state.commitment
        self.assertIsNotNone(commitment)
        assert commitment is not None
        facility = model.facilities_by_id[commitment.facility_id]
        self.assertEqual(commitment.facility_id, passenger.current_goal.facility_id)
        self.assertEqual(FacilityStage.ENTRY_GATE.value, passenger.current_goal.stage)
        if passenger in facility.queue:
            # A compiled decision region may coincide with the first safe
            # queue portal, so capture and admission can be immediate.
            self.assertEqual(AgentState.QUEUEING_GATE.value, passenger.state)
        else:
            reserved_index = passenger.facility_approach_slots_by_stage[
                FacilityStage.ENTRY_GATE.value
            ]
            self.assertIn(reserved_index, facility.portal_binding.approach_slot_indices)
            route_end = passenger.route[-1] if passenger.route else passenger.target
            reserved_slot = model._facility_approach_slot_position(
                facility,
                reserved_index,
            )
            self.assertLess(
                hypot(
                    route_end[0] - reserved_slot[0],
                    route_end[1] - reserved_slot[1],
                ),
                0.6,
            )

        for _ in range(10):
            if passenger.state != AgentState.ENTERING_STATION.value:
                break
            passenger.pos = passenger.target
            passenger.advance_after_movement(True)

        self.assertEqual(AgentState.QUEUEING_GATE.value, passenger.state)
        self.assertIn(passenger, facility.queue)

    def test_preselected_gate_route_targets_lane_slot_from_left_entry(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=29,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (10.0, 10.0)
        facility = model.gates[0]

        route = model.route_to_facility_queue(passenger, facility)

        gate_entry = model.layout_graph.station_graph.nodes["gate:gate_bank_a:entry"].position
        lane_slot = facility.spec.queue_layout.slot(0)
        self.assertEqual(1, len(route))
        self.assertLess(hypot(route[0][0] - lane_slot[0], route[0][1] - lane_slot[1]), 0.6)
        self.assertGreater(hypot(route[0][0] - gate_entry[0], route[0][1] - gate_entry[1]), 1.0)

    def test_gate_approach_keeps_stable_reserved_tactical_slot(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=29,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        gate = next(
            item
            for item in model.gates
            if len(item.portal_binding.approach_slot_indices) >= 2
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (10.0, 10.0)
        earlier = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model._reserve_facility_approach_slot(earlier, gate)
        reserved_index = model._reserve_facility_approach_slot(passenger, gate)

        empty_route = model.route_to_facility_queue(passenger, gate)

        reserved_slot = gate.spec.queue_layout.slot(reserved_index)
        self.assertLess(hypot(empty_route[-1][0] - reserved_slot[0], empty_route[-1][1] - reserved_slot[1]), 0.6)
        self.assertGreater(
            hypot(
                empty_route[-1][0] - gate.spec.queue_layout.slot(0)[0],
                empty_route[-1][1] - gate.spec.queue_layout.slot(0)[1],
            ),
            model.scenario.jupedsim_agent_radius_units
            * model.scenario.jupedsim_clearance_multiplier,
        )

        queued = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        for queued_passenger in queued:
            gate.join_queue(queued_passenger, authority="goal_graph")

        occupied_route = model.route_to_facility_queue(passenger, gate)

        self.assertLess(
            hypot(
                occupied_route[-1][0] - reserved_slot[0],
                occupied_route[-1][1] - reserved_slot[1],
            ),
            0.6,
        )

    def test_vertical_approach_keeps_stable_body_clear_tactical_slot(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=29,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        elevator = next(
            facility
            for facility in model.vertical_transports
            if isinstance(facility, ElevatorProcessAgent)
            and facility.spec.direction == "down"
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (20.0, 20.0)
        earlier = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model._reserve_facility_approach_slot(earlier, elevator)
        model._reserve_facility_approach_slot(passenger, elevator)

        empty_route = model.route_to_facility_queue(passenger, elevator)

        self.assertGreater(
            hypot(
                empty_route[-1][0] - elevator._service_entry_position(0)[0],
                empty_route[-1][1] - elevator._service_entry_position(0)[1],
            ),
            model.scenario.jupedsim_agent_radius_units
            * model.scenario.jupedsim_clearance_multiplier,
        )

        queued = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        for queued_passenger in queued:
            elevator.join_queue(queued_passenger, authority="goal_graph")

        occupied_route = model.route_to_facility_queue(passenger, elevator)

        self.assertLess(
            hypot(
                occupied_route[-1][0] - empty_route[-1][0],
                occupied_route[-1][1] - empty_route[-1][1],
            ),
            0.05,
        )

    def test_snapshot_queue_sync_preserves_body_clear_vertical_arrivals(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=30,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        elevator = next(
            facility
            for facility in model.vertical_transports
            if isinstance(facility, ElevatorProcessAgent)
            and facility.spec.direction == "down"
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        initial_positions = tuple(
            elevator._service_entry_position(index) for index in range(len(passengers))
        )
        for passenger, position in zip(passengers, initial_positions, strict=True):
            passenger.pos = position
            self.assertTrue(
                elevator.join_queue(
                    passenger,
                    authority="goal_graph",
                    settle_after_walking=True,
                )
            )

        model._sync_facility_queue_layouts_for_snapshot()

        self.assertEqual(initial_positions, tuple(passenger.pos for passenger in passengers))
        self.assertEqual(
            len(passengers),
            len(
                {
                    (round(passenger.pos[0], 2), round(passenger.pos[1], 2))
                    for passenger in passengers
                }
            ),
        )

    def test_facility_queue_crossing_guard_marks_capture_without_coordinate_snap(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=34,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        gate = next(gate for gate in model.gates if gate.facility_id.endswith("lane_5"))
        passenger.state = AgentState.ENTERING_STATION.value
        passenger.current_level_id = gate.spec.entry_level_id
        queue_target = model._safe_facility_queue_approach_target(passenger, gate)
        service_entry = gate.portal_entry_position
        dx = service_entry[0] - queue_target[0]
        dy = service_entry[1] - queue_target[1]
        length = hypot(dx, dy)
        unit = (dx / length, dy / length)
        passenger.pos = (
            queue_target[0] - unit[0] * 0.5,
            queue_target[1] - unit[1] * 0.5,
        )
        passenger.set_target(
            queue_target,
            goal_kind="queue_approach",
            goal_label=f"{gate.spec.label} queue approach",
            facility_id=gate.facility_id,
            stage=gate.spec.stage,
        )
        crossed_result = MovementResult(
            int(passenger.unique_id),
            (
                service_entry[0] + unit[0] * 0.2,
                service_entry[1] + unit[1] * 0.2,
            ),
            reached=False,
        )

        intercepted = model._intercept_facility_queue_crossing(passenger, crossed_result)

        self.assertTrue(intercepted.reached)
        self.assertEqual(crossed_result.position, intercepted.position)

    def test_facility_queue_crossing_guard_uses_current_queue_target(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=35,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        gate = next(gate for gate in model.gates if gate.facility_id.endswith("lane_6"))
        queued = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        gate.join_queue(queued, authority="goal_graph")
        passenger.state = AgentState.ENTERING_STATION.value
        passenger.current_level_id = gate.spec.entry_level_id
        passenger.pos = (25.12, 14.74)
        passenger.set_target(
            gate.spec.queue_layout.slot(0),
            goal_kind="queue_approach",
            goal_label=f"{gate.spec.label} queue approach",
            facility_id=gate.facility_id,
            stage=gate.spec.stage,
        )
        crossed_result = MovementResult(
            int(passenger.unique_id),
            (26.88, 15.09),
            reached=False,
        )

        intercepted = model._intercept_facility_queue_crossing(passenger, crossed_result)

        self.assertTrue(intercepted.reached)
        self.assertEqual(
            crossed_result.position,
            intercepted.position,
        )

    def test_diagonal_gate_queue_crossing_guard_uses_portal_axis(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=36,
            movement_backend=InstantMovementBackend(),
        )
        gate = model.gates[0]
        gate.spec = replace(
            gate.spec,
            position=(10.0, 10.0),
            exit_position=(12.0, 12.0),
            queue_layout=QueueLayout(
                anchor=(8.0, 8.0),
                per_row=1,
                col_step=(0.0, 0.0),
                row_step=(-0.7, -0.7),
                slots=((8.0, 8.0),),
            ),
            queue_crossing_guard=QueueCrossingGuard(
                enabled=True,
                tolerance_units=0.05,
                lane_half_width_units=0.6,
            ),
        )
        model._active_facility_portal_bindings[gate.facility_id] = (
            compile_micro_facility_portal_binding(gate.spec)
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.state = AgentState.ENTERING_STATION.value
        passenger.current_level_id = gate.spec.entry_level_id
        passenger.pos = (8.5, 8.5)
        passenger.set_target(
            gate.spec.queue_layout.slot(0),
            goal_kind="queue_approach",
            goal_label=f"{gate.spec.label} queue approach",
            facility_id=gate.facility_id,
            stage=gate.spec.stage,
        )

        crossed = model._intercept_facility_queue_crossing(
            passenger,
            MovementResult(int(passenger.unique_id), (10.2, 10.2), reached=False),
        )
        outside_lane = model._intercept_facility_queue_crossing(
            passenger,
            MovementResult(int(passenger.unique_id), (10.2, 12.5), reached=False),
        )

        self.assertTrue(crossed.reached)
        self.assertEqual((10.2, 10.2), crossed.position)
        self.assertFalse(outside_lane.reached)
        self.assertEqual((10.2, 12.5), outside_lane.position)

    def test_preselected_gate_route_skips_gate_bank_center_from_right_entry(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=29,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (70.0, 12.0)
        facility = model.gates[0]

        route = model.route_to_facility_queue(passenger, facility)

        gate_entry = model.layout_graph.station_graph.nodes["gate:gate_bank_a:entry"].position
        self.assertGreater(len(route), 1)
        for point in route[:-1]:
            self.assertGreater(hypot(point[0] - gate_entry[0], point[1] - gate_entry[1]), 1.0)
        self.assertLess(
            hypot(
                route[-1][0] - facility.spec.queue_anchor[0],
                route[-1][1] - facility.spec.queue_anchor[1],
            ),
            0.6,
        )

    def test_post_gate_route_to_stairs_stops_at_queue_before_service_entry(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=30,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        gate = next(gate for gate in model.gates if gate.facility_id.endswith("lane_1"))
        stairs = model.facilities_by_id[
            "vertical:stairs_a:down:b1_concourse:b2_platform"
        ]
        passenger.pos = gate.spec.exit_position
        passenger.current_level_id = gate.spec.exit_level_id
        passenger.state = AgentState.WALKING_TO_VERTICAL.value
        model._reserve_facility_approach_slot(passenger, stairs)

        route = model.route_to_facility_queue(passenger, stairs)

        self.assertEqual(1, len(route))
        self.assertGreater(
            hypot(route[0][0] - stairs.spec.position[0], route[0][1] - stairs.spec.position[1]),
            1.0,
        )
        self.assertEqual(
            model._safe_facility_queue_approach_target(passenger, stairs),
            route[-1],
        )
        self.assertGreater(min(point[1] for point in route), 13.0)

    def test_three_level_exit_station_completes_without_boarding(self) -> None:
        scenario = scenario_for("three_level_transfer")
        model = MetroStationModel(scenario, seed=7)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
        )
        model.passengers.append(passenger)

        for _ in range(220):
            model.step()
            if passenger.state == AgentState.DEPARTED.value:
                break

        self.assertEqual(AgentState.DEPARTED.value, passenger.state)
        self.assertEqual(0, model.boarded_persons)
        self.assertEqual(1, sum(gate.served_persons for gate in model.exit_gates))

    def test_single_platform_transfer_selects_platform_and_boards(self) -> None:
        scenario = scenario_for("two_level_island_platform")
        model = MetroStationModel(scenario, seed=9)
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.TRANSFER,
        )
        model.passengers.append(passenger)

        for _ in range(220):
            model.step()
            if passenger.state == AgentState.DEPARTED.value:
                break

        self.assertEqual(AgentState.DEPARTED.value, passenger.state)
        self.assertEqual("platform:default:down", passenger.assigned_platform_id)
        self.assertEqual(1, model.boarded_persons)

    def test_queue_and_platform_layout_use_lightweight_passive_motion(self) -> None:
        backend = LinearMovementBackend(step_units=0.25)
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=18,
            movement_backend=backend,
        )
        model.spawn_schedule.clear()

        queued = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        queued.pos = (1.0, 1.0)
        model.passengers.append(queued)
        model.gates[0].join_queue(queued, authority="goal_graph")
        queued_start = queued.pos

        model.gates[0]._layout_queue()

        self.assertEqual(0, backend.move_count)
        self.assertNotEqual(queued_start, queued.pos)

        waiting = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.TRANSFER,
        )
        waiting.pos = (1.0, 1.0)
        model.passengers.append(waiting)
        door = model.boarding_doors[0]
        door.join_queue(waiting, authority="goal_graph")
        waiting_start = waiting.pos

        door._layout_queue()

        self.assertEqual(0, backend.move_count)
        self.assertNotEqual(waiting_start, waiting.pos)

    def test_direct_passive_motion_respects_occupied_positions(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=29,
            movement_backend=InstantMovementBackend(),
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (10.0, 10.0)
        passenger.set_target((12.0, 10.0))

        reached = passenger.move_directly_toward_target(
            2.0,
            occupied_positions=[(12.0, 10.0)],
            min_clearance=0.5,
        )

        self.assertFalse(reached)
        self.assertNotEqual((12.0, 10.0), passenger.pos)
        self.assertGreaterEqual(hypot(passenger.pos[0] - 12.0, passenger.pos[1] - 10.0), 0.5)

    def test_direct_passive_motion_respects_continuous_swept_clearance(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=291,
            movement_backend=InstantMovementBackend(),
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.pos = (10.0, 10.0)
        passenger.set_target((12.0, 10.0))

        reached = passenger.move_directly_toward_target(
            2.0,
            occupied_positions=[(11.0, 10.4)],
            min_clearance=0.5,
        )

        self.assertFalse(reached)
        self.assertLessEqual(passenger.pos[0], 10.5)
        self.assertGreaterEqual(
            hypot(passenger.pos[0] - 11.0, passenger.pos[1] - 10.4),
            0.5,
        )

    def test_queue_layout_rejects_same_slot_overlap_without_backend_motion(self) -> None:
        backend = LinearMovementBackend(step_units=0.25)
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=30,
            movement_backend=backend,
        )
        gate = model.gates[0]
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        model.passengers.extend(passengers)
        shared_start = gate.spec.queue_layout.slot(0)
        for passenger in passengers:
            gate.join_queue(passenger, authority="goal_graph")
            passenger.pos = shared_start

        with self.assertRaisesRegex(RuntimeError, "co-located bodies"):
            gate._layout_queue()

        self.assertEqual(0, backend.move_count)
        self.assertEqual(passengers[0].pos, passengers[1].pos)

    def test_facility_service_states_do_not_enter_movement_backend(self) -> None:
        backend = LinearMovementBackend(step_units=0.25)
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=22,
            movement_backend=backend,
        )
        model.spawn_schedule.clear()
        passengers: list[PassengerAgent] = []
        for state in (
            AgentState.PASSING_GATE.value,
            AgentState.RIDING_VERTICAL.value,
            AgentState.BOARDING_TRAIN.value,
            AgentState.PASSING_EXIT_GATE.value,
            AgentState.QUEUEING_GATE.value,
        ):
            passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            passenger.state = state
            passenger.set_target((passenger.pos[0] + 5.0, passenger.pos[1]))
            passengers.append(passenger)

        walking = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        walking.state = AgentState.WALKING_TO_VERTICAL.value
        walking.set_target((walking.pos[0] + 5.0, walking.pos[1]))
        passengers.append(walking)

        results = backend.step_all(passengers)

        self.assertEqual(1, backend.move_count)
        self.assertEqual([(walking, results[0][1])], results)
        self.assertIn(walking.state, WALKING_STATES)

    def test_gate_service_reports_fact_without_advancing_journey(self) -> None:
        backend = LinearMovementBackend(step_units=0.25)
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=23,
            movement_backend=backend,
        )
        model.spawn_schedule.clear()
        gate = model.gates[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        gate.join_queue(passenger, authority="goal_graph")
        passenger.pos = gate.spec.queue_layout.slot(0)
        node_before_service = passenger.goal_runtime.state.current_node_id

        gate.step()

        self.assertEqual(0, backend.move_count)
        self.assertEqual(0, gate.served_persons)
        self.assertTrue(passenger.passive_facility_service)
        event = model.facility_service_events[0]
        model.step_index += 1
        start_snapshot = model.snapshot()
        start_passenger = next(
            item for item in start_snapshot["passengers"] if item["id"] == passenger.unique_id
        )
        self.assertEqual(event.start_time, start_snapshot["time_seconds"])
        self.assertAlmostEqual(event.start_position[0], start_passenger["x"], places=3)
        self.assertAlmostEqual(event.start_position[1], start_passenger["y"], places=3)
        self.assertEqual("being_served", start_passenger["goal"]["kind"])
        total_steps = gate.active_passes[0].total_steps
        for _ in range(total_steps):
            gate.step()
            model.step_index += 1

        self.assertEqual(1, gate.served_persons)
        self.assertEqual(AgentState.PASSING_GATE.value, passenger.state)
        self.assertEqual(
            node_before_service,
            passenger.goal_runtime.state.current_node_id,
        )
        self.assertEqual(1, len(model.facility_service_events))
        self.assertEqual(gate.facility_id, event.facility_id)
        self.assertEqual(gate.spec.queue_layout.slot(0), event.start_position)
        self.assertEqual(passenger.pos, event.end_position)
        end_snapshot = model.snapshot()
        end_passenger = next(
            item for item in end_snapshot["passengers"] if item["id"] == passenger.unique_id
        )
        self.assertGreaterEqual(end_snapshot["time_seconds"], event.end_time)
        self.assertLess(
            end_snapshot["time_seconds"] - event.end_time,
            model.scenario.tick_seconds,
        )
        self.assertAlmostEqual(event.end_position[0], end_passenger["x"], places=3)
        self.assertAlmostEqual(event.end_position[1], end_passenger["y"], places=3)
        self.assertLessEqual(
            hypot(
                event.end_position[0] - event.start_position[0],
                event.end_position[1] - event.start_position[1],
            ),
            model.scenario.jupedsim_desired_speed_mps
            * max(0.0, event.end_time - event.start_time)
            + 0.001,
        )

    def test_gate_service_defers_when_release_placement_is_blocked(self) -> None:
        backend = RejectingPlacementBackend(step_units=0.25)
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=25,
            movement_backend=backend,
        )
        model.spawn_schedule.clear()
        gate = model.gates[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        gate.join_queue(passenger, authority="goal_graph")
        passenger.pos = gate.spec.queue_layout.slot(0)

        gate.step()

        self.assertEqual(1, len(gate.queue))
        self.assertIs(passenger, gate.queue[0])
        self.assertEqual(0, gate.served_persons)
        self.assertEqual(AgentState.QUEUEING_GATE.value, passenger.state)
        self.assertEqual(0, len(model.facility_service_events))

    def test_train_headway_is_arrival_to_arrival_interval(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            initial_train_offset_seconds=10,
            train_dwell_seconds=20,
            train_headway_seconds=60,
        )
        model = MetroStationModel(
            scenario,
            seed=26,
            movement_backend=LinearMovementBackend(step_units=0.25),
        )
        model.spawn_schedule.clear()
        train = model.trains[0]
        arrivals: list[int] = []
        previous_state = train.state

        for step in range(16):
            model.step_index = step
            train.step()
            if train.state == "boarding" and previous_state != "boarding":
                arrivals.append(step)
            previous_state = train.state

        self.assertEqual([2, 14], arrivals)

    def test_departed_train_moves_load_to_last_departure_counter(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=26,
            movement_backend=LinearMovementBackend(step_units=0.25),
        )
        model.spawn_schedule.clear()
        train = model.trains[0]
        train.state = "boarding"
        train.current_load_persons = 17
        train.close_step = model.step_index

        train.step()

        self.assertEqual("away", train.state)
        self.assertEqual(0, train.current_load_persons)
        self.assertEqual(17, train.last_departed_load_persons)

    def test_same_tick_gate_release_uses_spaced_positions_and_times(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=24,
            movement_backend=LinearMovementBackend(step_units=0.25),
        )
        model.spawn_schedule.clear()
        gate = model.gates[0]
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(4)
        ]
        model.passengers.extend(passengers)
        for index, passenger in enumerate(passengers):
            gate.join_queue(passenger, authority="goal_graph")
            passenger.pos = gate.spec.queue_layout.slot(index)

        gate.step()

        self.assertEqual(0, gate.served_persons)
        self.assertEqual(4, len(gate.active_passes))
        total_steps = max(active.total_steps for active in gate.active_passes)
        for _ in range(total_steps * 8):
            gate.step()
            active_ids = {
                int(active.passenger.unique_id) for active in gate.active_passes
            }
            model.passengers[:] = [
                item
                for item in model.passengers
                if item not in passengers or int(item.unique_id) in active_ids
            ]
            if not gate.active_passes:
                break

        self.assertEqual(4, gate.served_persons)
        self.assertTrue(
            all(passenger.state == AgentState.PASSING_GATE.value for passenger in passengers)
        )
        min_distance = (
            model.scenario.jupedsim_agent_radius_units
            * model.scenario.jupedsim_clearance_multiplier
        )
        for left_index, left in enumerate(passengers):
            for right in passengers[left_index + 1 :]:
                self.assertGreaterEqual(
                    hypot(left.pos[0] - right.pos[0], left.pos[1] - right.pos[1]),
                    min_distance,
                )

        events = model.facility_service_events
        self.assertEqual(4, len(events))
        for event in events:
            traversal_distance = hypot(
                event.end_position[0] - event.start_position[0],
                event.end_position[1] - event.start_position[1],
            )
            self.assertGreaterEqual(
                event.end_time - event.start_time,
                traversal_distance / gate._walking_speed_m_s(),
            )
        self.assertEqual(
            {
                tuple(round(value, 3) for value in passenger.pos)
                for passenger in passengers
            },
            {
                tuple(round(value, 3) for value in event.end_position)
                for event in events
            },
        )
        self.assertEqual(
            [gate.spec.queue_layout.slot(index) for index in range(4)],
            [event.start_position for event in events],
        )
        for event in events:
            self.assertLessEqual(
                hypot(
                    event.end_position[0] - event.start_position[0],
                    event.end_position[1] - event.start_position[1],
                ),
                model.scenario.jupedsim_desired_speed_mps
                * (event.end_time - event.start_time)
                + 0.001,
            )

    def test_jupedsim_local_starts_keep_overlap_neighbors_as_adjusted_obstacles(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=25,
            movement_backend=LinearMovementBackend(step_units=0.25),
        )
        model.spawn_schedule.clear()
        gate = model.gates[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        neighbor = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.state = AgentState.WALKING_TO_VERTICAL.value
        neighbor.state = AgentState.WALKING_TO_VERTICAL.value
        passenger.current_level_id = gate.spec.exit_level_id
        neighbor.current_level_id = gate.spec.exit_level_id
        passenger.pos = gate.spec.exit_position
        neighbor.pos = gate.spec.exit_position
        passenger.set_target((gate.spec.exit_position[0] + 5.0, gate.spec.exit_position[1]))
        neighbor.set_target((gate.spec.exit_position[0] + 5.0, gate.spec.exit_position[1]))
        model.passengers.extend([passenger, neighbor])
        model.rebuild_spatial_index()
        backend = JuPedSimMovementBackend(
            SimpleNamespace(status=SimpleNamespace(available=True, message="ok")),
            strict=False,
        )

        starts = backend._local_starts(passenger)

        self.assertEqual(2, len(starts))
        self.assertEqual(passenger.pos, starts[0])
        self.assertNotEqual(passenger.pos, starts[1])

    def test_facility_waits_until_queue_head_reaches_service_slot(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=26,
            movement_backend=LinearMovementBackend(step_units=0.25),
        )
        model.spawn_schedule.clear()
        transport = model.vertical_transports[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        transport.join_queue(passenger, authority="goal_graph")
        passenger.pos = (1.0, 1.0)

        transport.step()

        self.assertEqual(AgentState.QUEUEING_VERTICAL.value, passenger.state)
        self.assertEqual([passenger], transport.queue)
        self.assertEqual([], model.facility_service_events)

    def test_boarding_door_service_reports_fact_without_completing_journey(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            audit_enabled=True,
            audit_print_events=False,
        )
        model = MetroStationModel(scenario, seed=19, movement_backend=InstantMovementBackend())
        model.spawn_schedule.clear()
        train = model.train
        train.state = "boarding"
        train.close_step = model.step_index + 20
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        door = model.boarding_doors[0]
        door.join_queue(passenger, authority="goal_graph")
        passenger.pos = door.spec.queue_layout.slot(0)

        door.step(train)

        self.assertIn(AgentState.BOARDING_TRAIN.value, PASSIVE_STATES)
        self.assertNotIn(AgentState.BOARDING_TRAIN.value, CROWD_INTERACTION_STATES)
        self.assertEqual(AgentState.BOARDING_TRAIN.value, passenger.state)
        self.assertIn(passenger, model.passengers)
        self.assertEqual(0, model.boarded_persons)
        self.assertEqual(0, train.current_load_persons)
        self.assertEqual(1, train.reserved_boarding_persons)
        self.assertEqual(0, door.served_persons)
        self.assertEqual(1, len(model.facility_service_events))
        for _ in range(20):
            if not door.active_boardings:
                break
            model.step_index += 1
            door.step(train)

        self.assertEqual([], door.active_boardings)
        self.assertEqual(0, model.boarded_persons)
        self.assertEqual(1, train.current_load_persons)
        self.assertEqual(0, train.reserved_boarding_persons)
        self.assertEqual(1, door.served_persons)
        self.assertEqual(door.spec.position, passenger.pos)
        event = model.facility_service_events[0]
        self.assertEqual(FacilityKind.TRAIN_DOOR.value, event.facility_kind)
        self.assertEqual(door.facility_id, event.facility_id)
        self.assertEqual((passenger.unique_id,), event.passenger_ids)
        self.assertEqual(passenger.pos, event.end_position)

    def test_progress_monitor_does_not_replan_active_service(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            audit_enabled=True,
            audit_print_events=False,
            progress_stall_seconds=5.0,
        )
        model = MetroStationModel(scenario, seed=20, movement_backend=LinearMovementBackend())
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        gate = model.gates[0]
        passenger.begin_facility_service(gate.spec)

        model.progress_monitor.observe(model, [passenger])
        model.step_index = 2
        model.progress_monitor.observe(model, [passenger])

        self.assertNotIn(
            "passenger_replanned_service_transition",
            model.audit.summary(),
        )
        self.assertIsNone(passenger.last_replan_reason)
        self.assertEqual(AgentState.PASSING_GATE.value, passenger.state)

    def test_movement_stall_before_decision_region_recomputes_physical_route(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=20,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        rerouted_target = (passenger.pos[0] + 2.0, passenger.pos[1])
        router = model.goal_coordinator.executor.region_router

        with patch.object(router, "route", return_value=(rerouted_target,)) as route:
            changed = model.goal_coordinator.replan(
                passenger,
                reason="movement_stalled",
            )

        self.assertTrue(changed)
        route.assert_called_once()
        self.assertEqual(rerouted_target, passenger.target)
        self.assertEqual("goal_region", passenger.current_goal.kind)
        self.assertEqual("movement_stalled", passenger.last_replan_reason)

    def test_movement_stall_on_use_stage_releases_provisional_slot_and_reroutes(
        self,
    ) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=201,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        node = next(
            item
            for item in passenger.goal_runtime.graph.nodes
            if item.kind == "use_facility_stage"
            and item.facility_stage == FacilityStage.ENTRY_GATE.value
        )
        passenger.goal_runtime.state = replace(
            passenger.goal_runtime.state,
            current_node_id=node.node_id,
            interaction_state="approach_decision_region",
            current_stage=node.facility_stage,
            commitment=None,
            queued_facility_id=None,
        )
        gate = model.gates[0]
        model._reserve_facility_approach_slot(passenger, gate)
        rerouted_target = (passenger.pos[0] + 1.0, passenger.pos[1])
        router = model.goal_coordinator.executor.region_router

        with patch.object(router, "route", return_value=(rerouted_target,)) as route:
            changed = model.goal_coordinator.replan(
                passenger,
                reason="movement_stalled",
            )

        self.assertTrue(changed)
        route.assert_called_once()
        self.assertEqual({}, passenger.facility_approach_slots_by_stage)
        self.assertIsNone(
            gate.queue.approach_slot_reservation(int(passenger.unique_id))
        )
        self.assertEqual(rerouted_target, passenger.target)

    def test_movement_stall_preserves_owned_decision_holding_target(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=202,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        node = next(
            item
            for item in passenger.goal_runtime.graph.nodes
            if item.kind == "use_facility_stage"
            and item.facility_stage == FacilityStage.ENTRY_GATE.value
        )
        passenger.goal_runtime.state = replace(
            passenger.goal_runtime.state,
            current_node_id=node.node_id,
            interaction_state="approach_decision_region",
            current_stage=node.facility_stage,
            commitment=None,
            queued_facility_id=None,
        )
        router = model.goal_coordinator.executor.region_router
        active = model.goal_coordinator._active_decision_route(
            passenger,
            node,
            passenger.goal_runtime.state,
        )
        self.assertIsNotNone(active)
        region_id, _stage = active
        base_region = router._base_region(region_id)
        holding_target = (passenger.pos[0] + 2.0, passenger.pos[1])
        passenger.decision_holding_target_by_region[base_region] = holding_target

        with (
            patch.object(router, "route", return_value=(holding_target,)) as route,
            patch.object(router, "clear_decision_context") as clear_context,
            patch.object(
                model,
                "_clear_all_facility_targeting_reservations",
            ) as clear_facility,
        ):
            changed = model.goal_coordinator.replan(
                passenger,
                reason="movement_stalled",
            )

        self.assertTrue(changed)
        route.assert_called_once()
        clear_context.assert_not_called()
        clear_facility.assert_not_called()
        self.assertEqual(
            holding_target,
            passenger.decision_holding_target_by_region[base_region],
        )
        self.assertEqual(holding_target, passenger.target)

    def test_generated_passengers_clear_without_runtime_replans(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station", minutes=12),
            audit_enabled=True,
            audit_print_events=False,
            entry_count_hour=0,
            exit_count_hour=0,
            initial_train_offset_seconds=5,
            train_headway_seconds=90,
            train_dwell_seconds=60,
            queue_replan_wait_seconds=999.0,
            progress_stall_seconds=60.0,
        )
        backend = LinearMovementBackend(step_units=4.0)
        model = MetroStationModel(scenario, seed=21, movement_backend=backend)
        model.spawn_schedule.clear()
        passengers: list[PassengerAgent] = []
        for intent, count in (
            (AgentIntent.ENTER_AND_BOARD, 10),
            (AgentIntent.EXIT_STATION, 6),
            (AgentIntent.TRANSFER, 4),
        ):
            for _ in range(count):
                passenger = PassengerAgent(
                    model,
                    group_size=1,
                    created_step=0,
                    intent=intent,
                )
                passengers.append(passenger)
                model.passengers.append(passenger)

        for _ in range(240):
            model.step()
            if not model.passengers:
                break

        self.assertFalse(model.passengers)
        self.assertEqual(14, model.boarded_persons)
        self.assertGreater(backend.move_count, 0)
        recovery_codes = {
            code
            for code in model.audit.summary()
            if code.startswith("passenger_replanned")
            or code.startswith("passenger_replan")
            or code == "passenger_completed_stalled_boarding"
        }
        self.assertEqual(set(), recovery_codes)


class IntegrationSurfaceTests(unittest.TestCase):
    def test_render_payload_includes_compiled_station_graph(self) -> None:
        payload = geometry_payload(scenario_for("single_level_terminal"))
        self.assertEqual("design_document", payload["source"])
        self.assertTrue(payload["graph_nodes"])
        self.assertTrue(payload["graph_edges"])
        self.assertTrue(any(edge["kind"] == "service" for edge in payload["graph_edges"]))

    def test_jupedsim_backend_name_maps_to_batched_backend_when_available(self) -> None:
        scenario = replace(scenario_for("single_level_terminal"), movement_backend_name="jupedsim")
        model = MetroStationModel(scenario, seed=3)
        if model.jupedsim.status.available:
            self.assertIsInstance(model.movement_backend, BatchedJuPedSimMovementBackend)
        else:
            self.assertNotIsInstance(model.movement_backend, BatchedJuPedSimMovementBackend)

    def test_jupedsim_social_force_tick_moves_agent_when_available(self) -> None:
        adapter = JuPedSimAdapter()
        if not adapter.status.available:
            self.skipTest(adapter.status.message)

        positions = adapter.simulate_walk_tick(
            starts=[(1.0, 2.5)],
            target=(9.0, 2.5),
            width=10.0,
            height=5.0,
            iterations=150,
            radius=0.18,
            target_radius=0.45,
            operational_model="social_force",
        )

        self.assertEqual(1, len(positions))
        self.assertGreater(positions[0][0], 1.5)
        self.assertAlmostEqual(2.5, positions[0][1], delta=0.2)

    def test_jupedsim_backend_keeps_agent_in_persistent_session(self) -> None:
        scenario = replace(
            scenario_for("single_level_terminal"),
            jupedsim_iterations_per_tick=10,
        )
        model = MetroStationModel(scenario, seed=31)
        if not model.jupedsim.status.available:
            self.skipTest(model.jupedsim.status.message)
        self.assertIsInstance(model.movement_backend, BatchedJuPedSimMovementBackend)

        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        self.assertGreater(
            hypot(passenger.target[0] - passenger.pos[0], passenger.target[1] - passenger.pos[1]),
            scenario.jupedsim_target_radius_units,
        )

        first = model.movement_backend.step_all([passenger])
        passenger.apply_movement_result(first[0][1])
        session_key = model.movement_backend._session_keys_by_passenger[int(passenger.unique_id)]
        session = model.movement_backend._sessions[session_key]
        sim_agent_id = session._agent_ids[int(passenger.unique_id)]

        second = model.movement_backend.step_all([passenger])

        self.assertEqual(1, len(second))
        self.assertEqual(sim_agent_id, session._agent_ids[int(passenger.unique_id)])

    def test_frame_metrics_include_jupedsim_operational_model(self) -> None:
        scenario = replace(
            scenario_for("single_level_terminal"),
            jupedsim_operational_model="social_force",
        )
        model = MetroStationModel(scenario, seed=3)
        frame = model.snapshot()

        self.assertEqual("social_force", frame["metrics"]["jupedsim_operational_model"])

    def test_admin_agent_has_no_facility_choice_policy_surface(self) -> None:
        model = MetroStationModel(scenario_for("single_level_terminal", admins=1), seed=5)
        self.assertEqual(1, len(model.admin_agents))
        self.assertFalse(hasattr(model, "facility_choice_policy"))

    def test_exit_demand_uses_train_alighting_schedule(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station", minutes=5),
            entry_count_hour=12,
            exit_count_hour=12,
            transfer_count_hour=12,
        )
        scheduler = DemandScheduler.from_scenario(scenario, Random(4))

        entry_groups = sum(
            due.get(AgentIntent.ENTER_AND_BOARD.value, 0)
            for due in scheduler.spawn_schedule.values()
        )
        exit_groups = sum(
            due.get(AgentIntent.EXIT_STATION.value, 0)
            for due in scheduler.spawn_schedule.values()
        )
        transfer_groups = sum(
            due.get(AgentIntent.TRANSFER.value, 0)
            for due in scheduler.spawn_schedule.values()
        )
        alighting_groups = sum(scheduler.alighting_schedule.values())
        first_arrival_step = round(
            scenario.initial_train_offset_seconds / scenario.tick_seconds
        )

        self.assertEqual(1, entry_groups)
        self.assertEqual(0, exit_groups)
        self.assertEqual(1, transfer_groups)
        self.assertEqual(1, alighting_groups)
        self.assertGreaterEqual(min(scheduler.alighting_schedule), first_arrival_step)

    def test_alighting_spawn_cell_avoids_platform_passengers_and_same_batch(self) -> None:
        model = MetroStationModel(scenario_for("single_level_terminal"), seed=42)
        door = model.boarding_doors[0]
        level_id = door.spec.exit_level_id or door.spec.entry_level_id
        self.assertIsNotNone(level_id)
        assert level_id is not None
        first = model._alighting_spawn_position(door, 0, reserved_positions=[])
        self.assertIsNotNone(first)
        assert first is not None
        blocker = model._spawn_passenger(
            AgentIntent.EXIT_STATION,
            initial_position=first,
            initial_level_id=level_id,
        )

        second = model._alighting_spawn_position(door, 0, reserved_positions=[])
        self.assertIsNotNone(second)
        assert second is not None
        third = model._alighting_spawn_position(
            door,
            1,
            reserved_positions=[(second, level_id)],
        )
        self.assertIsNotNone(third)
        assert third is not None
        clearance = model.scenario.jupedsim_agent_radius_units * 2.0

        self.assertGreaterEqual(hypot(second[0] - blocker.pos[0], second[1] - blocker.pos[1]), clearance)
        self.assertGreaterEqual(hypot(third[0] - blocker.pos[0], third[1] - blocker.pos[1]), clearance)
        self.assertGreaterEqual(hypot(third[0] - second[0], third[1] - second[1]), clearance)

    def test_clearance_tail_does_not_expand_spawn_schedule(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station", minutes=8),
            demand_minutes=2,
            entry_count_hour=120,
            exit_count_hour=60,
            transfer_count_hour=90,
        )
        model = MetroStationModel(scenario, seed=4)

        entry_groups = sum(
            due.get(AgentIntent.ENTER_AND_BOARD.value, 0) for due in model.spawn_schedule.values()
        )
        exit_groups = sum(
            due.get(AgentIntent.EXIT_STATION.value, 0) for due in model.spawn_schedule.values()
        )
        transfer_groups = sum(
            due.get(AgentIntent.TRANSFER.value, 0) for due in model.spawn_schedule.values()
        )
        alighting_groups = sum(model.alighting_schedule.values())
        first_arrival_step = round(
            scenario.initial_train_offset_seconds / scenario.tick_seconds
        )

        self.assertEqual(96, scenario.horizon_steps)
        self.assertEqual(24, scenario.demand_steps)
        self.assertEqual(4, entry_groups)
        self.assertEqual(0, exit_groups)
        self.assertEqual(3, transfer_groups)
        self.assertEqual(2, alighting_groups)
        self.assertLess(max(model.spawn_schedule), scenario.demand_steps)
        self.assertGreaterEqual(min(model.alighting_schedule), first_arrival_step)

    def test_transfer_demand_can_clear_with_clearance_tail(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform", minutes=6),
            demand_minutes=1,
            entry_count_hour=0,
            exit_count_hour=0,
            transfer_count_hour=60,
            initial_train_offset_seconds=5,
            train_headway_seconds=60,
            train_dwell_seconds=45,
        )
        model = MetroStationModel(
            scenario,
            seed=17,
            movement_backend=LinearMovementBackend(step_units=4.0),
        )

        frames = model.run()
        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=model.facilities,
            service_events=model.facility_service_events,
        )

        self.assertGreaterEqual(model.spawned_persons_by_intent[AgentIntent.TRANSFER.value], 1)
        self.assertEqual(0, len(model.passengers))
        self.assertEqual(
            model.spawned_persons_by_intent[AgentIntent.TRANSFER.value],
            model.boarded_persons,
        )
        self.assertTrue(payload["clearance_audit"]["cleared"])
        self.assertEqual(1, payload["clearance_audit"]["spawned_transfer_persons"])

    def test_exit_passengers_spawn_only_while_train_is_boarding(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station", minutes=4),
            entry_count_hour=0,
            exit_count_hour=120,
            initial_train_offset_seconds=75,
            train_headway_seconds=240,
            train_dwell_seconds=35,
        )
        model = MetroStationModel(scenario, seed=4, movement_backend=LinearMovementBackend())
        first_arrival_step = round(
            scenario.initial_train_offset_seconds / scenario.tick_seconds
        )

        for _ in range(first_arrival_step):
            model.step()

        self.assertEqual(0, model.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value])
        self.assertTrue(all(train.state == "away" for train in model.trains))

        model.step()

        self.assertGreater(model.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value], 0)
        self.assertTrue(any(train.state == "boarding" for train in model.trains))
        self.assertTrue(
            all(
                passenger.intent != AgentIntent.EXIT_STATION.value
                or passenger.created_step >= first_arrival_step
                for passenger in model.passengers
            )
        )

    def test_facility_specs_instantiate_concrete_runtime_classes(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=4)

        self.assertTrue(all(isinstance(facility, FacilityAgent) for facility in model.facilities))
        self.assertTrue(
            all(isinstance(facility, FacilityProcessAgent) for facility in model.facilities)
        )
        self.assertTrue(all(isinstance(gate, GateProcessAgent) for gate in model.gates))
        self.assertTrue(all(isinstance(gate, GateProcessAgent) for gate in model.exit_gates))
        self.assertTrue(
            any(
                isinstance(transport, EscalatorProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            any(
                isinstance(transport, ElevatorProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            any(
                isinstance(transport, StairsProcessAgent)
                for transport in model.vertical_transports
            )
        )
        self.assertTrue(
            all(isinstance(door, BoardingDoorProcessAgent) for door in model.boarding_doors)
        )
        with self.assertRaises(TypeError):
            FacilityProcessAgent(model, spec=model.gates[0].spec)

    def test_amenity_facility_is_not_a_process_agent(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=40)
        amenity = AmenityFacilityAgent(model, spec=amenity_spec())

        self.assertIsInstance(amenity, FacilityAgent)
        self.assertNotIsInstance(amenity, FacilityProcessAgent)
        self.assertFalse(hasattr(amenity, "join_queue"))
        self.assertEqual(0, amenity.queue_persons)
        self.assertEqual(0, amenity.served_persons)
        self.assertEqual(0.0, amenity.effective_service_persons_per_min)

    def test_amenity_facility_can_live_in_model_facilities_without_stage_leakage(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=41)
        amenity = AmenityFacilityAgent(
            model,
            spec=amenity_spec(stage=FacilityStage.ENTRY_GATE.value),
        )
        model.facilities.append(amenity)
        model.facilities_by_id[amenity.facility_id] = amenity

        self.assertIn(amenity, model.facilities)
        self.assertNotIn(amenity, model._facilities_for_stage(FacilityStage.ENTRY_GATE))
        self.assertTrue(all(isinstance(gate, FacilityProcessAgent) for gate in model.gates))

    def test_facility_snapshot_handles_amenity_defaults(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=42)
        amenity = AmenityFacilityAgent(model, spec=amenity_spec())

        snapshot = FacilitySnapshot.from_facility(amenity)

        self.assertEqual(amenity.facility_id, snapshot.id)
        self.assertEqual(FacilityKind.AMENITY.value, snapshot.kind)
        self.assertEqual(0, snapshot.queue_persons)
        self.assertEqual(0, snapshot.active_persons)
        self.assertEqual(0, snapshot.served_persons)
        self.assertEqual(0.0, snapshot.service_persons_per_min)
        self.assertEqual(0, snapshot.queue_capacity)

    def test_design_vertical_speeds_follow_scenario_operations(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_speed_units_per_tick=7.5,
            escalator_speed_units_per_tick=3.1,
            stairs_speed_units_per_tick=1.2,
            elevator_speed_m_s=1.1,
            escalator_speed_m_s=0.6,
            stairs_speed_m_s=0.8,
        )
        model = MetroStationModel(scenario, seed=4)

        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        stairs = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, StairsProcessAgent)
        )

        self.assertEqual(7.5, elevator.spec.speed_units_per_tick)
        self.assertEqual(3.1, escalator.spec.speed_units_per_tick)
        self.assertEqual(1.2, stairs.spec.speed_units_per_tick)
        self.assertEqual(1.1, elevator.spec.travel_speed_m_s)
        self.assertEqual(0.6, escalator.spec.travel_speed_m_s)
        self.assertEqual(0.8, stairs.spec.travel_speed_m_s)

    def test_design_escalator_queue_front_matches_service_entry(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=43)

        escalators = [
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        ]

        self.assertGreater(len(escalators), 0)
        for escalator in escalators:
            with self.subTest(escalator=escalator.facility_id):
                slot = escalator.spec.queue_layout.slot(0)
                self.assertLess(
                    hypot(
                        slot[0] - escalator.spec.position[0],
                        slot[1] - escalator.spec.position[1],
                    ),
                    0.001,
                )

    def test_escalator_service_axis_supports_multiple_angles(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=44,
            movement_backend=InstantMovementBackend(),
        )
        vectors = {
            "east": (8.0, 0.0),
            "north": (0.0, 8.0),
            "diagonal": (6.0, 6.0),
            "reverse_diagonal": (-5.0, 7.0),
        }

        for name, vector in vectors.items():
            with self.subTest(angle=name):
                start = (35.0, 21.0)
                end = (start[0] + vector[0], start[1] + vector[1])
                distance = hypot(vector[0], vector[1])
                queue_step = (-vector[0] / distance * 0.8, -vector[1] / distance * 0.8)
                slots = (
                    start,
                    (start[0] + queue_step[0], start[1] + queue_step[1]),
                    (start[0] + queue_step[0] * 2.0, start[1] + queue_step[1] * 2.0),
                )
                spec = FacilitySpec(
                    facility_id=f"vertical:test_escalator:{name}:down:b1:b2",
                    stage=FacilityStage.VERTICAL_TRANSFER.value,
                    label=f"Test escalator {name}",
                    kind=FacilityKind.ESCALATOR.value,
                    direction="down",
                    position=start,
                    queue_layout=QueueLayout(
                        anchor=start,
                        per_row=1,
                        col_step=(0.0, 0.0),
                        row_step=queue_step,
                        slots=slots,
                    ),
                    exit_position=end,
                    service_persons_per_min=600,
                    queue_state=AgentState.QUEUEING_VERTICAL.value,
                    service_state=AgentState.RIDING_VERTICAL.value,
                    release_route=(start, end),
                    speed_units_per_tick=1.0,
                    entry_level_id="b1_concourse",
                    exit_level_id="b1_concourse",
                    vertical_config=VerticalFacilityConfig(
                        escalator=EscalatorConfig(stand_capacity_ppm=600)
                    ),
                    traversal_width_m=1.2,
                )
                escalator = EscalatorProcessAgent(model, spec=spec)
                model._active_facility_portal_bindings[spec.facility_id] = (
                    compile_micro_facility_portal_binding(spec)
                )
                passenger = PassengerAgent(
                    model,
                    group_size=1,
                    created_step=0,
                    intent=AgentIntent.ENTER_AND_BOARD,
                )
                passenger.current_level_id = spec.entry_level_id
                passenger.pos = spec.position
                escalator.join_queue(passenger, authority="goal_graph")

                escalator.step()
                self.assertEqual(1, len(escalator.active_rides))
                ride = escalator.active_rides[0]
                service_unit = (vector[0] / distance, vector[1] / distance)
                start_along = (passenger.pos[0] - start[0]) * service_unit[0] + (
                    passenger.pos[1] - start[1]
                ) * service_unit[1]
                start_lateral = (
                    (passenger.pos[0] - start[0]) * -service_unit[1]
                    + (passenger.pos[1] - start[1]) * service_unit[0]
                )
                self.assertAlmostEqual(0.0, start_along)
                self.assertAlmostEqual(ride.lateral_offset, start_lateral)

                escalator.step()
                mid = passenger.pos
                along = (mid[0] - start[0]) * service_unit[0] + (
                    mid[1] - start[1]
                ) * service_unit[1]
                lateral = abs(
                    (mid[0] - start[0]) * -service_unit[1]
                    + (mid[1] - start[1]) * service_unit[0]
                )

                self.assertGreater(along, 0.0)
                self.assertLess(along, distance)
                self.assertAlmostEqual(abs(ride.lateral_offset), lateral)

    def test_design_elevator_dispatch_policy_follows_scenario_operations(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=10,
            elevator_min_dispatch_persons=7,
            elevator_max_dispatch_wait_seconds=22.0,
        )
        model = MetroStationModel(scenario, seed=7, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )

        config = elevator.spec.vertical_config.elevator
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(10, config.batch_capacity)
        self.assertEqual(7, config.min_dispatch_persons)
        self.assertEqual(22.0, config.max_dispatch_wait_seconds)

    def test_elevator_runtime_batches_passengers_by_cabin_cycle(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=2,
            elevator_min_dispatch_persons=1,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(scenario, seed=8, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        model.passengers.extend(passengers)
        for index, passenger in enumerate(passengers):
            elevator.join_queue(passenger, authority="goal_graph")
            passenger.pos = elevator._service_entry_position(index)

        elevator.step()

        self.assertEqual(1, len(elevator.queue))
        self.assertEqual(2, elevator.cabin_load_persons)
        self.assertEqual(0, elevator.served_persons)
        self.assertEqual(0, elevator.departed_cabins)
        self.assertEqual("boarding", elevator.cabin_state)

        for _ in range(32):
            if elevator.departed_cabins >= 1:
                break
            elevator.step()

        self.assertEqual(1, len(elevator.queue))
        self.assertEqual(0, elevator.served_persons)
        self.assertEqual(1, elevator.departed_cabins)
        self.assertEqual("moving", elevator.cabin_state)
        self.assertTrue(all(passenger.passive_facility_service for passenger in passengers[:2]))
        self.assertEqual(1, len(model.facility_service_events))

        for _ in range(64):
            if elevator.served_persons >= 2 and elevator.cabin_load_persons == 1:
                break
            elevator.step()

        self.assertEqual(0, len(elevator.queue))
        self.assertEqual(1, elevator.cabin_load_persons)
        self.assertEqual(2, elevator.served_persons)
        self.assertEqual(1, elevator.departed_cabins)
        self.assertEqual("boarding", elevator.cabin_state)

        for _ in range(32):
            if elevator.departed_cabins >= 2:
                break
            elevator.step()

        self.assertEqual(2, elevator.served_persons)
        self.assertEqual(2, elevator.departed_cabins)
        self.assertEqual("moving", elevator.cabin_state)

        for _ in range(64):
            if elevator.served_persons >= 3 and elevator.cabin_state == "idle":
                break
            elevator.step()

        self.assertEqual(3, elevator.served_persons)
        self.assertEqual("idle", elevator.cabin_state)

    def test_elevator_event_boundaries_match_post_tick_states(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=2,
            elevator_min_dispatch_persons=1,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(
            scenario,
            seed=81,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        elevator.join_queue(passenger, authority="goal_graph")
        passenger.pos = elevator._service_entry_position(0)

        elevator.step()
        event = model.facility_service_events[0]
        model.step_index += 1
        state_by_time = {model.current_time_seconds: elevator.cabin_state}
        passive_by_time = {model.current_time_seconds: passenger.passive_facility_service}

        self.assertEqual(event.start_time, model.current_time_seconds)
        self.assertEqual("boarding", elevator.cabin_state)
        self.assertTrue(passenger.passive_facility_service)

        for _ in range(elevator.cycle_steps + 2):
            if not elevator.cabin_passengers:
                break
            elevator.step()
            model.step_index += 1
            state_by_time[model.current_time_seconds] = elevator.cabin_state
            passive_by_time[model.current_time_seconds] = passenger.passive_facility_service

        self.assertEqual("moving", state_by_time[event.board_end_time])
        expected_arrival_states = (
            {"unloading"}
            if event.arrive_time < event.end_time
            else {"returning", "idle"}
        )
        self.assertIn(state_by_time[event.arrive_time], expected_arrival_states)
        first_commit_at_or_after_end = min(
            time_seconds
            for time_seconds in passive_by_time
            if time_seconds >= event.end_time
        )
        self.assertFalse(passive_by_time[first_commit_at_or_after_end])
        self.assertLessEqual(event.end_time, model.current_time_seconds)
        self.assertLess(model.current_time_seconds - event.end_time, scenario.tick_seconds)

    def test_elevator_hard_deadline_dispatches_ready_fifo_prefix(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=4,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(scenario, seed=18, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(4)
        ]
        model.passengers.extend(passengers)
        for index, passenger in enumerate(passengers):
            elevator.join_queue(passenger, authority="goal_graph")
            passenger.pos = elevator._service_entry_position(index)
        passengers[-1].pos = (
            elevator._service_entry_position(3)[0] + 10.0,
            elevator._service_entry_position(3)[1],
        )

        elevator.step()

        self.assertEqual("waiting", elevator.cabin_state)
        self.assertEqual([], elevator.cabin_passengers)
        self.assertEqual(4, len(elevator.queue))

        elevator.boarding_wait_remaining_steps = 0
        elevator.step()

        self.assertEqual("boarding", elevator.cabin_state)
        self.assertEqual(3, elevator.cabin_load_persons)
        self.assertEqual(passengers[:3], elevator.cabin_passengers)
        self.assertEqual([passengers[-1]], elevator.queue)

        passengers[-1].pos = elevator._service_entry_position(3)
        self.assertEqual([passengers[-1]], elevator.queue)

    def test_elevator_waits_for_minimum_dispatch_load_before_departing(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=4,
            elevator_min_dispatch_persons=3,
            elevator_max_dispatch_wait_seconds=20.0,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(scenario, seed=28, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        model.passengers.extend(passengers)
        for index, passenger in enumerate(passengers[:2]):
            elevator.join_queue(passenger, authority="goal_graph")
            passenger.pos = elevator._service_entry_position(index)

        elevator.step()

        self.assertEqual("waiting", elevator.cabin_state)
        self.assertEqual([], elevator.cabin_passengers)
        self.assertEqual(2, len(elevator.queue))

        elevator.join_queue(passengers[2], authority="goal_graph")
        passengers[2].pos = elevator._service_entry_position(2)
        elevator.step()

        self.assertEqual("boarding", elevator.cabin_state)
        self.assertEqual(3, elevator.cabin_load_persons)
        self.assertEqual([], elevator.queue)

    def test_elevator_hard_dispatch_deadline_is_not_extended_by_nearby_demand(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=4,
            elevator_min_dispatch_persons=3,
            elevator_max_dispatch_wait_seconds=20.0,
            elevator_cycle_seconds=20.0,
        )
        model = MetroStationModel(scenario, seed=29, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        model.passengers.extend(passengers)
        for passenger in passengers:
            passenger.prefers_elevator = True
            passenger.current_level_id = elevator.spec.entry_level_id
        for index, passenger in enumerate(passengers[:2]):
            elevator.join_queue(passenger, authority="goal_graph")
            passenger.pos = elevator._service_entry_position(index)
        passengers[2].state = AgentState.WALKING_TO_VERTICAL.value
        passengers[2].pos = (
            elevator.spec.queue_anchor[0] + 4.0,
            elevator.spec.queue_anchor[1],
        )

        elevator.step()
        elevator.boarding_wait_remaining_steps = 0
        elevator.step()

        self.assertEqual("boarding", elevator.cabin_state)
        self.assertEqual(2, elevator.cabin_load_persons)
        self.assertEqual([], elevator.queue)

    def test_elevator_return_trip_blocks_next_boarding_cycle(self) -> None:
        scenario = replace(
            scenario_for("two_level_island_platform"),
            elevator_cabin_capacity_persons=1,
            elevator_cycle_seconds=10.0,
        )
        model = MetroStationModel(scenario, seed=19, movement_backend=InstantMovementBackend())
        elevator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, ElevatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        model.passengers.extend(passengers)
        for index, passenger in enumerate(passengers):
            elevator.join_queue(passenger, authority="goal_graph")
            passenger.pos = elevator._service_entry_position(index)

        elevator.step()
        elevator.step()
        for _ in range(elevator.travel_steps):
            elevator.step()
        for _ in range(elevator.unload_steps + 1):
            if elevator.cabin_state != "unloading":
                break
            elevator.step()

        self.assertEqual("returning", elevator.cabin_state)
        self.assertEqual(1, elevator.served_persons)
        self.assertEqual(1, len(elevator.queue))

        for _ in range(elevator.return_steps - 1):
            elevator.step()

        self.assertEqual("returning", elevator.cabin_state)

        elevator.step()

        self.assertEqual("boarding", elevator.cabin_state)
        self.assertEqual(1, elevator.cabin_load_persons)

    def test_escalator_mode_controls_capacity_and_availability(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=9)
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )

        stand_capacity = escalator.effective_service_persons_per_min
        escalator.set_mode(EscalatorMode.WALK)

        self.assertGreater(escalator.effective_service_persons_per_min, stand_capacity)
        self.assertTrue(escalator.is_available_for_choice)

        escalator.set_mode(EscalatorMode.BLOCKED)

        self.assertEqual(0, escalator.effective_service_persons_per_min)
        self.assertFalse(escalator.is_open)
        self.assertFalse(escalator.is_available_for_choice)

    def test_escalator_fixed_ride_time_uses_mode_speed_factor(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=16)
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        escalator.spec = replace(
            escalator.spec,
            vertical_config=VerticalFacilityConfig(
                escalator=EscalatorConfig(ride_time_seconds=20.0)
            ),
        )

        stand_steps = escalator._ride_steps_for_mode()
        escalator.set_mode(EscalatorMode.WALK)
        walk_steps = escalator._ride_steps_for_mode()
        escalator.set_mode(EscalatorMode.OFF)
        off_steps = escalator._ride_steps_for_mode()

        self.assertLess(walk_steps, stand_steps)
        self.assertGreater(off_steps, stand_steps)

    def test_escalator_service_is_passive_until_ride_duration_completes(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=10,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        passenger.plan = model.plan_for_intent(AgentIntent.ENTER_AND_BOARD)
        model.passengers.append(passenger)
        escalator.join_queue(passenger, authority="goal_graph")
        passenger.pos = escalator.spec.queue_layout.slot(0)

        escalator.step()

        self.assertEqual(0, len(escalator.queue))
        self.assertTrue(passenger.passive_facility_service)
        self.assertEqual(AgentState.RIDING_VERTICAL.value, passenger.state)
        self.assertEqual(1, len(model.facility_service_events))
        event = model.facility_service_events[0]
        model.step_index += 1
        start_snapshot = model.snapshot()
        start_passenger = next(
            item for item in start_snapshot["passengers"] if item["id"] == passenger.unique_id
        )
        self.assertEqual(event.start_time, start_snapshot["time_seconds"])
        self.assertLessEqual(
            hypot(
                event.start_position[0] - start_passenger["x"],
                event.start_position[1] - start_passenger["y"],
            ),
            0.2,
        )

        remaining_steps = escalator.active_rides[0].remaining_steps
        suppressed_on_completion = False
        for _ in range(remaining_steps):
            escalator.step()
            suppressed_on_completion = passenger.movement_suppressed_this_step()
            model.step_index += 1

        self.assertFalse(passenger.passive_facility_service)
        self.assertEqual(AgentState.RIDING_VERTICAL.value, passenger.state)
        self.assertTrue(suppressed_on_completion)
        self.assertEqual(1, escalator.served_persons)
        end_snapshot = model.snapshot()
        end_passenger = next(
            item for item in end_snapshot["passengers"] if item["id"] == passenger.unique_id
        )
        # Physical completion may fall between Mesa snapshots.  The event
        # keeps the exact service boundary while state is published at the
        # first following process boundary.
        self.assertGreaterEqual(end_snapshot["time_seconds"], event.end_time)
        self.assertLess(
            end_snapshot["time_seconds"] - event.end_time,
            model.scenario.tick_seconds,
        )
        self.assertLessEqual(
            hypot(
                event.end_position[0] - end_passenger["x"],
                event.end_position[1] - end_passenger["y"],
            ),
            1.5,
        )

    def test_vertical_active_ride_updates_position_before_finish(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=17,
            movement_backend=InstantMovementBackend(),
        )
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        passenger.pos = escalator.spec.queue_layout.slot(0)
        escalator.queue.join(passenger)
        escalator.queue.pop(0)

        escalator._start_passive_ride(passenger, mode="stand", ride_steps=4)
        escalator._advance_active_rides()

        self.assertTrue(passenger.passive_facility_service)
        self.assertNotEqual(escalator.spec.position, passenger.pos)
        self.assertNotEqual(escalator.spec.exit_position, passenger.pos)

    def test_simultaneous_vertical_riders_keep_distinct_physical_lanes(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=17,
            movement_backend=InstantMovementBackend(),
        )
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, StairsProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        model.passengers.extend(passengers)
        for release_index, passenger in enumerate(passengers):
            passenger.pos = escalator._safe_queue_slot(release_index)
            escalator.queue.join(passenger)
            escalator.queue.pop(0)
            escalator._start_passive_ride(
                passenger,
                mode="stand",
                ride_steps=4,
                release_index=release_index,
                release_count=len(passengers),
            )

        start_positions = {tuple(round(value, 3) for value in item.pos) for item in passengers}
        escalator._advance_active_rides()
        moving_positions = {tuple(round(value, 3) for value in item.pos) for item in passengers}
        offsets = [ride.lateral_offset for ride in escalator.active_rides]

        self.assertEqual(2, len(start_positions))
        self.assertEqual(2, len(moving_positions))
        self.assertEqual(2, len(set(offsets)))
        half_width = float(escalator.spec.traversal_width_m) / 2.0
        body_radius = model.scenario.jupedsim_agent_radius_units
        self.assertTrue(all(abs(offset) + body_radius <= half_width for offset in offsets))
        self.assertGreaterEqual(
            hypot(
                passengers[0].pos[0] - passengers[1].pos[0],
                passengers[0].pos[1] - passengers[1].pos[1],
            ),
            escalator._release_min_distance() - 1e-6,
        )

    def test_single_vertical_riders_use_the_physical_centreline(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=17,
            movement_backend=InstantMovementBackend(),
        )
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]

        offsets = [
            escalator._ride_lateral_offset(
                passenger,
                release_index=0,
                release_count=1,
            )
            for passenger in passengers
        ]

        self.assertEqual([0.0, 0.0], offsets)
        self.assertEqual(
            offsets[0],
            escalator._ride_lateral_offset(
                passengers[0],
                release_index=0,
                release_count=1,
            ),
        )

    def test_vertical_release_positions_are_spaced_for_same_tick_arrivals(self) -> None:
        model = MetroStationModel(
            scenario_for("visual_demo_station"),
            seed=15,
            movement_backend=InstantMovementBackend(),
        )
        escalator = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, EscalatorProcessAgent)
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(3)
        ]
        model.passengers.extend(passengers)
        for passenger in passengers:
            passenger.pos = escalator.spec.queue_layout.slot(0)
            escalator.queue.join(passenger)
            escalator.queue.pop(0)
            escalator._start_passive_ride(passenger, mode="stand", ride_steps=1)

        escalator._advance_active_rides()

        positions = [passenger.pos for passenger in passengers]
        rounded_positions = {(round(x, 3), round(y, 3)) for x, y in positions}
        min_distance = escalator._release_min_distance()

        self.assertEqual(3, len(rounded_positions))
        self.assertEqual(escalator.spec.exit_position, positions[0])
        for left_index, left in enumerate(positions):
            for right in positions[left_index + 1 :]:
                self.assertGreaterEqual(
                    hypot(left[0] - right[0], left[1] - right[1]),
                    min_distance - 1e-6,
                )

    def test_stairs_bidirectional_conflict_reduces_effective_capacity(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=11)
        stairs = [
            transport
            for transport in model.vertical_transports
            if isinstance(transport, StairsProcessAgent)
        ]
        self.assertGreaterEqual(len(stairs), 2)
        down = next(stair for stair in stairs if stair.spec.direction == "down")
        up = next(stair for stair in stairs if stair.spec.direction == "up")

        unloaded_capacity = down.effective_service_persons_per_min
        for _ in range(6):
            passenger = PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.EXIT_STATION,
            )
            up.join_queue(passenger, authority="goal_graph")

        self.assertLess(down.effective_service_persons_per_min, unloaded_capacity)
        self.assertGreater(up.fatigue_cost, down.fatigue_cost)
        self.assertLess(up.travel_speed_units_per_tick, down.travel_speed_units_per_tick)

    def test_stairs_service_preserves_fifo_when_queue_head_is_not_ready(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=15,
            movement_backend=InstantMovementBackend(),
        )
        model.spawn_schedule.clear()
        stairs = next(
            transport
            for transport in model.vertical_transports
            if isinstance(transport, StairsProcessAgent)
            and transport.spec.direction == "down"
        )
        blocked = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        ready = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.extend([blocked, ready])
        stairs.join_queue(blocked, authority="goal_graph")
        stairs.join_queue(ready, authority="goal_graph")
        slot_0 = stairs.spec.queue_layout.slot(0)
        blocked.pos = (slot_0[0] + 10.0, slot_0[1] + 10.0)
        # Readiness cannot let a later member overtake a single ordered queue.
        # Multi-lane stairs require explicit per-lane queues before independent
        # frontage service can preserve FIFO within each lane.
        ready.pos = stairs._service_entry_position(0)
        stairs.service_credit = 2.0

        stairs._serve_queue()

        self.assertIn(blocked, stairs.queue)
        self.assertIn(ready, stairs.queue)
        self.assertFalse(stairs.active_rides)

    def test_stairs_opposing_active_rides_slow_current_rides(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=14,
            movement_backend=InstantMovementBackend(),
        )
        stairs = [
            transport
            for transport in model.vertical_transports
            if isinstance(transport, StairsProcessAgent)
        ]
        down = next(stair for stair in stairs if stair.spec.direction == "down")
        up = next(stair for stair in stairs if stair.spec.direction == "up")
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        opposing = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.EXIT_STATION,
        )
        model.passengers.extend([passenger, opposing])

        passenger.pos = down.spec.queue_layout.slot(0)
        down.queue.join(passenger)
        down.queue.pop(0)
        opposing.pos = up.spec.queue_layout.slot(0)
        up.queue.join(opposing)
        up.queue.pop(0)
        down._start_passive_ride(passenger, mode="walk", ride_steps=10)
        up._start_passive_ride(opposing, mode="walk", ride_steps=10)
        ride = down.active_rides[0]
        down._advance_active_rides()

        self.assertLess(ride.progress_steps, 1.0)
        self.assertGreater(ride.remaining_steps, 9)

    def test_vertical_specs_include_type_specific_config(self) -> None:
        model = MetroStationModel(scenario_for("two_level_island_platform"), seed=12)
        configs = {transport.spec.kind: transport.spec.vertical_config for transport in model.vertical_transports}

        self.assertIsNotNone(configs[FacilityKind.ESCALATOR.value].escalator)
        self.assertIsNotNone(configs[FacilityKind.ELEVATOR.value].elevator)
        self.assertIsNotNone(configs[FacilityKind.STAIRS.value].stairs)


class ExtractedUtilityTests(unittest.TestCase):
    def test_logit_picker_prefers_lower_generalized_cost(self) -> None:
        picks = [
            pick_logit(
                ["cheap", "expensive"],
                Random(seed),
                lambda item: 0.0 if item == "cheap" else 10.0,
                sensitivity=2.0,
            )
            for seed in range(20)
        ]

        self.assertEqual(["cheap"] * 20, picks)

    def test_facility_queue_enforces_capacity_and_counts_persons(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=38,
            movement_backend=InstantMovementBackend(),
        )
        passengers = [
            PassengerAgent(
                model,
                group_size=1,
                created_step=0,
                intent=AgentIntent.ENTER_AND_BOARD,
            )
            for _ in range(2)
        ]
        queue = FacilityQueue(
            QueueLayout((0.0, 0.0), 1, (1.0, 0.0), (0.0, 1.0)),
            max_length=1,
        )

        self.assertTrue(queue.join(passengers[0]))
        self.assertTrue(queue.join(passengers[0]))
        self.assertFalse(queue.join(passengers[1]))
        self.assertEqual([passengers[0]], queue)
        self.assertEqual(1, queue.persons)
        self.assertTrue(queue.is_full)

    def test_facility_process_agent_uses_facility_queue_object(self) -> None:
        model = MetroStationModel(
            scenario_for("two_level_island_platform"),
            seed=39,
            movement_backend=InstantMovementBackend(),
        )
        gate = model.gates[0]
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )

        gate.join_queue(passenger, authority="goal_graph")

        self.assertIsInstance(gate.queue, FacilityQueue)
        self.assertEqual([passenger], gate.queue)
        self.assertEqual(passenger.group_size, gate.queue_persons)

    def test_vertical_choice_model_prefers_easy_escalator_over_nearby_stairs(self) -> None:
        origin = (0.861, 0.765)
        options = (
            VerticalChoiceOption("up_escalator_2", "escalator", (0.815, 0.716)),
            VerticalChoiceOption("stairs_up", "stairs", (0.850, 0.708)),
        )

        probabilities = vertical_choice_probabilities(origin, options)

        self.assertGreater(probabilities["up_escalator_2"], 0.98)
        self.assertLess(probabilities["stairs_up"], 0.02)

    def test_vertical_choice_model_still_uses_nearest_escalator_bank(self) -> None:
        origin = (0.251, 0.765)
        options = (
            VerticalChoiceOption("up_escalator_1", "escalator", (0.288, 0.716)),
            VerticalChoiceOption("up_escalator_2", "escalator", (0.815, 0.716)),
        )

        probabilities = vertical_choice_probabilities(origin, options)

        self.assertGreater(probabilities["up_escalator_1"], 0.99)

    def test_progress_monitor_does_not_replan_elevator_batch_wait(self) -> None:
        scenario = replace(
            scenario_for("visual_demo_station"),
            audit_enabled=True,
            audit_print_events=False,
            queue_replan_wait_seconds=5.0,
            elevator_max_dispatch_wait_seconds=0.0,
            elevator_boarding_seconds=0.1,
            elevator_cycle_seconds=0.1,
            elevator_unload_seconds=0.1,
        )
        model = MetroStationModel(scenario, seed=13)
        model.spawn_schedule.clear()
        elevator = next(
            facility
            for facility in model.vertical_transports
            if isinstance(facility, ElevatorProcessAgent)
            and facility.spec.direction == "down"
        )
        elevator.spec = replace(
            elevator.spec,
            vertical_config=VerticalFacilityConfig(
                elevator=ElevatorConfig(
                    batch_capacity=1,
                    min_dispatch_persons=1,
                    boarding_seconds=0.1,
                    travel_seconds=0.1,
                    unload_seconds=0.1,
                    return_seconds=0.1,
                )
            ),
        )
        # The minimum-jerk cabin profile may make boarding materially longer
        # than the authored lower bound.  Ten seconds is beyond every authored
        # phase but still inside this physically feasible effective cycle.
        elevator._effective_boarding_duration_seconds = 15.0
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )
        model.passengers.append(passenger)
        elevator.join_queue(passenger, authority="goal_graph")
        old_facility_id = passenger.assigned_facility_id

        model.progress_monitor.observe(model, [passenger])
        model.step_index = 2
        model.progress_monitor.observe(model, [passenger])

        self.assertGreater(elevator.effective_cycle_seconds, 10.0)
        self.assertEqual(old_facility_id, passenger.assigned_facility_id)
        self.assertIn(passenger, elevator.queue)
        self.assertNotIn("passenger_replanned_facility", model.audit.summary())
        self.assertIsNone(passenger.last_replan_reason)

    def test_boarding_door_filter_prefers_assigned_platform(self) -> None:
        passenger = SimpleNamespace(
            assigned_platform_id="platform:a:down",
            assigned_line_id="a",
            assigned_direction="down",
        )
        matching = SimpleNamespace(
            spec=SimpleNamespace(
                platform_id="platform:a:down",
                line_id="a",
                direction="down",
                entry_level_id=None,
            )
        )
        other = SimpleNamespace(
            spec=SimpleNamespace(
                platform_id="platform:b:up",
                line_id="b",
                direction="up",
                entry_level_id=None,
            )
        )

        self.assertEqual(
            [matching], filter_boarding_doors_for_passenger(passenger, [other, matching])
        )

    def test_boarding_door_filter_returns_empty_for_assigned_platform_mismatch(self) -> None:
        passenger = SimpleNamespace(
            assigned_platform_id="platform:missing:down",
            assigned_line_id="a",
            assigned_direction="down",
        )
        door = SimpleNamespace(
            spec=SimpleNamespace(
                platform_id="platform:a:down",
                line_id="a",
                direction="down",
                entry_level_id="b2_platform",
            )
        )

        self.assertEqual([], filter_boarding_doors_for_passenger(passenger, [door]))

    def test_platform_filter_returns_empty_for_target_line_mismatch(self) -> None:
        passenger = SimpleNamespace(target_line_id="line_3", target_direction="down")
        platforms = [
            SimpleNamespace(platform_id="p1", line_id="line_1", direction="down"),
            SimpleNamespace(platform_id="p2", line_id="line_2", direction="down"),
        ]

        self.assertEqual([], filter_platforms_for_passenger(passenger, platforms))

    def test_platform_filter_and_least_loaded_picker_share_tie_breaking(self) -> None:
        passenger = SimpleNamespace(target_line_id="line_2", target_direction="up")
        platforms = [
            SimpleNamespace(
                platform_id="p1", line_id="line_1", direction="down", waiting_persons=0
            ),
            SimpleNamespace(platform_id="p2", line_id="line_2", direction="up", waiting_persons=3),
            SimpleNamespace(platform_id="p3", line_id="line_2", direction="up", waiting_persons=1),
        ]

        filtered = filter_platforms_for_passenger(passenger, platforms)
        self.assertEqual(["p2", "p3"], [platform.platform_id for platform in filtered])
        self.assertEqual(
            "p3",
            pick_least_loaded(filtered, Random(3), lambda item: item.waiting_persons).platform_id,
        )


class VisualDemoGeometryTests(unittest.TestCase):
    def test_explicit_queue_slots_extend_instead_of_reusing_fixed_points(self) -> None:
        layout = QueueLayout(
            anchor=(0.0, 0.0),
            per_row=2,
            col_step=(0.0, 0.0),
            row_step=(0.0, 1.0),
            slots=((0.0, 0.0), (1.0, 0.0)),
        )

        self.assertEqual(layout.slot(0), (0.0, 0.0))
        self.assertEqual(layout.slot(1), (1.0, 0.0))
        self.assertEqual(layout.slot(2), (0.0, 1.0))
        self.assertEqual(layout.slot(3), (1.0, 1.0))

    def test_fare_barrier_blocks_between_gate_openings(self) -> None:
        geometry = load_station_geometry()

        self.assertFalse(geometry.covers(Point(meters((0.190, 0.352)))))
        self.assertTrue(geometry.covers(Point(meters((0.210, 0.352)))))
        self.assertFalse(
            geometry.buffer(0.02).covers(
                LineString([meters((0.500, 0.330)), meters((0.500, 0.375))])
            )
        )

    def test_visual_demo_vertical_graph_nodes_are_level_specific_and_walkable(self) -> None:
        graph = StationGraph.from_design(create_design("visual_demo_station"))
        geometry = load_station_geometry()

        self.assertNotEqual(
            graph.nodes["vertical:down_escalator_a:b1_concourse"].position,
            graph.nodes["vertical:down_escalator_a:b2_platform"].position,
        )
        for node in graph.nodes_matching(facility_stage=FacilityStage.VERTICAL_TRANSFER.value):
            with self.subTest(node=node.node_id):
                self.assertTrue(geometry.covers(Point(node.position)))

    def test_visual_demo_zone_graph_nodes_are_walkable(self) -> None:
        graph = StationGraph.from_design(create_design("visual_demo_station"))
        geometry = load_station_geometry()

        for node in graph.nodes_matching(kind="zone"):
            with self.subTest(node=node.node_id):
                self.assertTrue(geometry.covers(Point(node.position)))

    def test_visual_demo_platform_waiting_slots_are_walkable(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        geometry = load_station_geometry()

        for index in range(120):
            with self.subTest(index=index):
                self.assertTrue(
                    geometry.covers(Point(model.layout_graph.platform_waiting_position(index)))
                )

    def test_visual_demo_platform_waiting_slots_are_near_train_doors(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        document = create_design("visual_demo_station")
        door_points = [
            element.geometry.center()
            for element in document.elements
            if element.kind == "platform_edge"
        ]
        train_edge_min_y = meters((0.0, 0.72))[1]

        for index in range(120):
            slot = model.layout_graph.platform_waiting_position(index)
            nearest_door_distance = min(abs(slot[0] - door[0]) for door in door_points)
            with self.subTest(index=index, slot=slot):
                self.assertGreaterEqual(slot[1], train_edge_min_y)
                self.assertLessEqual(nearest_door_distance, 4.6)

    def test_visual_demo_platform_waiting_slots_do_not_repeat_under_load(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        positions = [model.layout_graph.platform_waiting_position(index) for index in range(260)]
        rounded = {(round(x, 3), round(y, 3)) for x, y in positions}

        self.assertEqual(len(rounded), len(positions))

    def test_visual_demo_facility_queue_slots_are_walkable(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        geometry = load_station_geometry()

        for facility in model.facilities:
            slots = facility.spec.queue_layout.slots
            with self.subTest(facility=facility.spec.facility_id):
                self.assertTrue(slots)
            for slot in slots[:32]:
                with self.subTest(facility=facility.spec.facility_id, slot=slot):
                    self.assertTrue(geometry.covers(Point(slot)))

    def test_visual_demo_vertical_queues_stay_behind_service_entry(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)

        vertical_kinds = {
            FacilityKind.ESCALATOR.value,
            FacilityKind.ELEVATOR.value,
            FacilityKind.STAIRS.value,
        }
        for facility in model.facilities:
            spec = facility.spec
            if spec.kind not in vertical_kinds:
                continue
            # Queue approach direction is a same-level design fact.  The
            # connector exit lives on another level, so its plan-view delta is
            # not a valid local entrance heading for stacked floor plans.
            forward_x = -spec.queue_layout.row_step[0]
            forward_y = -spec.queue_layout.row_step[1]
            length = hypot(forward_x, forward_y)
            forward_x /= length
            forward_y /= length
            lateral_x = -forward_y
            lateral_y = forward_x

            for slot in spec.queue_layout.slots[1:32]:
                progress = (
                    (slot[0] - spec.position[0]) * forward_x
                    + (slot[1] - spec.position[1]) * forward_y
                )
                lateral_distance = abs(
                    (slot[0] - spec.position[0]) * lateral_x
                    + (slot[1] - spec.position[1]) * lateral_y
                )
                with self.subTest(facility=spec.facility_id, slot=slot):
                    self.assertTrue(
                        progress <= 0.15 or lateral_distance >= 0.4 - 1e-9
                    )

    def test_visual_demo_gate_banks_compile_to_individual_lanes(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        document = create_design("visual_demo_station")
        entry_gate_box = document.element_by_id()["gate_bank_a"].geometry.bounds()
        exit_gate_box = document.element_by_id()["exit_gate_bank_a"].geometry.bounds()

        self.assertEqual(6, len(model.gates))
        self.assertEqual(4, len(model.exit_gates))
        self.assertEqual(
            6,
            len({round(gate.spec.position[0], 3) for gate in model.gates}),
        )
        self.assertEqual(
            4,
            len({round(gate.spec.position[0], 3) for gate in model.exit_gates}),
        )
        for gate in model.gates:
            with self.subTest(gate=gate.spec.facility_id):
                self.assertAlmostEqual(gate.spec.position[1], entry_gate_box[1])
                self.assertAlmostEqual(gate.spec.exit_position[1], entry_gate_box[3])
                self.assertAlmostEqual(gate.spec.position[0], gate.spec.exit_position[0])
        for gate in model.exit_gates:
            with self.subTest(gate=gate.spec.facility_id):
                self.assertAlmostEqual(gate.spec.position[1], exit_gate_box[3])
                self.assertAlmostEqual(gate.spec.exit_position[1], exit_gate_box[1])
                self.assertAlmostEqual(gate.spec.position[0], gate.spec.exit_position[0])

    def test_visual_demo_queue_payload_exports_gate_lanes(self) -> None:
        scenario = scenario_for("visual_demo_station")
        model = MetroStationModel(scenario, seed=2)

        payload = mesa_frames_to_visual_tracks(
            frames=[],
            scenario=scenario,
            facilities=model.facilities,
        )
        entry_queues = [
            queue for queue in payload["queue_layouts"] if queue["kind"] == "entry_gate"
        ]
        exit_queues = [
            queue for queue in payload["queue_layouts"] if queue["kind"] == "exit_gate"
        ]

        self.assertEqual(6, len(entry_queues))
        self.assertEqual(4, len(exit_queues))
        self.assertTrue(all("_lane_" in queue["id"] for queue in entry_queues))
        self.assertEqual(6, len({tuple(queue["exit"]) for queue in entry_queues}))
        self.assertTrue(all(abs(queue["exit"][1] - 0.300) <= 0.001 for queue in entry_queues))
        self.assertTrue(all(abs(queue["exit"][1] - 0.316) <= 0.001 for queue in exit_queues))
        for queue, gate_point in zip(
            sorted(entry_queues, key=lambda item: item["exit"][0]),
            payload["layout"]["control_points"]["gates"],
        ):
            with self.subTest(queue=queue["id"]):
                self.assertAlmostEqual(gate_point[0], queue["exit"][0], delta=0.001)
                self.assertAlmostEqual(
                    queue["exit"][0],
                    queue["slots"][0][0],
                    delta=0.001,
                )
                self.assertLess(queue["slots"][0][1], queue["exit"][1])
                self.assertEqual(1, len({round(slot[0], 4) for slot in queue["slots"][:4]}))
        for queue in exit_queues:
            with self.subTest(queue=queue["id"]):
                self.assertAlmostEqual(queue["exit"][0], queue["slots"][0][0], delta=0.001)
                self.assertGreater(queue["slots"][0][1], queue["exit"][1])

    def test_visual_demo_decision_regions_are_exported(self) -> None:
        payload = layout_payload()
        geometry = load_station_geometry()
        regions = payload["decision_regions"]
        by_id = {region["id"]: region for region in regions}

        self.assertIn("entry_gate_decision", by_id)
        self.assertIn("vertical_transfer_decision", by_id)
        self.assertIn("platform_boarding_decision", by_id)
        self.assertIn("exit_gate_decision", by_id)
        self.assertGreaterEqual(by_id["exit_gate_decision"]["points"][0][1], 0.318)
        for region in regions:
            points = region["points"]
            centroid = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
            with self.subTest(region=region["id"]):
                self.assertTrue(geometry.covers(Point(meters(centroid))))

    def test_visual_demo_exit_gate_decision_route_stays_on_paid_side(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)

        route = model.layout_graph.route_for_key(
            RouteKey.AFTER_EXIT_VERTICAL.value,
            meters((0.600, 0.430)),
        )

        self.assertGreaterEqual(route[-1][1], meters((0.0, 0.330))[1])
        for facility in model.vertical_transports:
            if facility.spec.direction not in {"up", "both"}:
                continue
            with self.subTest(facility=facility.facility_id):
                route = model.layout_graph.route_for_key(
                    RouteKey.AFTER_EXIT_VERTICAL.value,
                    facility.spec.exit_position,
                )
                self.assertEqual(1, len(route))
                self.assertGreaterEqual(route[-1][1], meters((0.0, 0.330))[1])

    def test_visual_demo_after_entry_gate_route_stays_in_paid_area(self) -> None:
        model = MetroStationModel(scenario_for("visual_demo_station"), seed=2)
        context = SimpleNamespace(current_level_id="b1_concourse")

        for facility in model.gates:
            with self.subTest(facility=facility.facility_id):
                route = model.layout_graph.route_for_key(
                    RouteKey.AFTER_GATE.value,
                    facility.spec.exit_position,
                    context,
                )

                self.assertTrue(route)
                self.assertTrue(all(point[1] >= meters((0.0, 0.350))[1] for point in route))
                self.assertTrue(all(point[0] >= meters((0.145, 0.0))[0] for point in route))

    def test_jupedsim_start_position_projects_from_boundary_to_walkable_core(self) -> None:
        geometry = load_station_geometry()
        adapter = JuPedSimAdapter()
        boundary_near = (20.51583939244577, 29.94093838319245)

        projected = adapter._safe_agent_position(geometry, boundary_near, 0.18)

        self.assertTrue(geometry.buffer(-0.18).covers(Point(projected)))

    def test_region_flow_compiles_source_to_queue_capture_apron(self) -> None:
        queue = next(item for item in FACILITY_QUEUES if item.name == "down_escalator_2_queue")
        plan = build_region_capture_flow(
            name="test.right.vertical_capture",
            source=(0.720, 0.360),
            queue_spec=queue,
            queue_stage_id=42,
            capture_aprons=QUEUE_CAPTURE_APRONS_N,
        )

        self.assertEqual(42, plan.target_queue_stage_id)
        self.assertEqual("down_escalator_2_queue", plan.target_facility)
        self.assertGreaterEqual(len(plan.portals), 1)
        self.assertEqual("down_escalator_2_queue", plan.portals[-1].facility)
        self.assertLess(plan.portals[-1].center[0], 0.620)
        self.assertGreater(plan.portals[-1].radius_m, plan.portals[0].radius_m)

    def test_point_capture_flow_supports_runtime_queue_without_spec(self) -> None:
        plan = build_point_capture_flow(
            name="test.boarding.capture",
            source=(0.330, 0.715),
            capture=(0.360, 0.735),
            target_queue_stage_id=99,
            target_facility="boarding_door_1",
            portal_count=1,
        )

        self.assertEqual(99, plan.target_queue_stage_id)
        self.assertEqual("boarding_door_1", plan.target_facility)
        self.assertEqual(1, len(plan.portals))
        self.assertEqual("boarding_door_1", plan.portals[-1].facility)

    def test_queue_attractiveness_field_ranks_reachable_lower_cost_option(self) -> None:
        field = QueueAttractivenessField()
        current = QueueFieldCandidate(
            stage_id=1,
            facility="boarding_door_1",
            distance_m=2.0,
            load=10,
            service_interval_s=0.5,
            current=True,
            reachable=True,
        )
        alternative = QueueFieldCandidate(
            stage_id=2,
            facility="boarding_door_2",
            distance_m=3.0,
            load=1,
            service_interval_s=0.5,
            current=False,
            reachable=True,
        )
        blocked = QueueFieldCandidate(
            stage_id=3,
            facility="boarding_door_3",
            distance_m=1.0,
            load=0,
            service_interval_s=0.5,
            current=False,
            reachable=False,
        )

        scores = field.rank((current, alternative, blocked))

        self.assertEqual(2, scores[0].stage_id)
        self.assertEqual(float("inf"), scores[-1].cost)

    def test_grid_floor_field_routes_around_fare_barrier(self) -> None:
        geometry = load_station_geometry()
        grid = GridFloorField.from_geometry(geometry, cell_size_m=1.0)
        source = meters((0.500, 0.330))
        target = meters((0.500, 0.375))
        field = grid.distance_field((target,))

        direct = Point(source).distance(Point(target))
        cost = field.cost_at(source)

        self.assertGreater(cost, direct * 2.0)
        self.assertNotEqual((0.0, 0.0), field.descent_vector(source))

    def test_grid_floor_field_dynamic_penalty_raises_cost(self) -> None:
        geometry = load_station_geometry()
        grid = GridFloorField.from_geometry(geometry, cell_size_m=1.0)
        source = meters((0.500, 0.330))
        target = meters((0.500, 0.375))
        baseline = grid.distance_field((target,)).cost_at(source)
        penalty = grid.density_penalty((meters((0.500, 0.345)),), radius_cells=3, weight=6.0)
        crowded = grid.distance_field((target,), dynamic_penalty=penalty).cost_at(source)

        self.assertGreater(crowded, baseline)

    def test_entry_gate_release_uses_narrow_service_portal(self) -> None:
        runtime = NativeQueueRuntime(
            name="entry_gate_1_queue",
            source="gate_queue_state",
            color="#2f89ff",
            stage_id=1,
            service_interval=1.65,
            next_service=0.0,
            spec=GATE_QUEUE_SPECS[0],
        )

        self.assertEqual(ENTRY_GATE_PORTAL_RADIUS_M, post_gate_portal_radius(runtime))
        self.assertLess(ENTRY_GATE_PORTAL_RADIUS_M, POST_GATE_RADIUS_M)

    def test_queue_field_switching_is_limited_to_boarding_doors(self) -> None:
        boarding = NativeQueueRuntime(
            name="boarding_door_1",
            source="boarding_queue_native",
            color="#ffd166",
            stage_id=1,
            service_interval=0.42,
            next_service=0.0,
        )
        gate = NativeQueueRuntime(
            name="entry_gate_1_queue",
            source="gate_queue_state",
            color="#2f89ff",
            stage_id=2,
            service_interval=1.65,
            next_service=0.0,
            spec=GATE_QUEUE_SPECS[0],
        )

        self.assertTrue(queue_field_switching_is_enabled(boarding))
        self.assertFalse(queue_field_switching_is_enabled(gate))


if __name__ == "__main__":
    unittest.main()
