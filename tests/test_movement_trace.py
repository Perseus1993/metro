from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from metro_station.adapters.simulation.movement.jps_adapter import (
    JuPedSimAdapter,
    JuPedSimRemovalRecord,
    JuPedSimWalkingSession,
)
from metro_station.adapters.simulation.movement.contracts import MovementRequest
from metro_station.adapters.simulation.movement.backend import (
    JuPedSimMovementBackend,
    MovementResult,
)
from metro_station.adapters.simulation.movement.facility_motion_trace import (
    FacilityMotionTraceRecorder,
)
from metro_station.adapters.simulation.movement.trajectory_trace import MovementTraceRecorder
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.planning.plan import AgentIntent, AgentState
from metro_station.adapters.simulation.planning.plan import WALKING_STATES
from metro_station.adapters.simulation.runtime.contracts import SimulationTrace
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    mesa_frames_to_visual_tracks,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_acceptance.presentation_fidelity_gate import (
    analyze_presentation_fidelity,
)


@dataclass
class _FakeAgent:
    id: int
    position: tuple[float, float]


def test_movement_request_separates_tactical_and_final_arrival_radius() -> None:
    scenario = SimpleNamespace(
        jupedsim_agent_radius_units=0.18,
        jupedsim_target_radius_units=0.45,
        jupedsim_desired_speed_mps=1.2,
    )
    model = SimpleNamespace(
        scenario=scenario,
        desired_walk_speed_mps=lambda _passenger: 1.2,
    )
    passenger = SimpleNamespace(
        unique_id=7,
        pos=(1.0, 1.0),
        target=(2.0, 1.0),
        route=[(3.0, 1.0)],
        current_level_id="b1",
        model=model,
    )

    tactical = MovementRequest.from_passenger(passenger)
    passenger.route_waypoint_radius_override = 0.396
    body_clear_tactical = MovementRequest.from_passenger(passenger)
    passenger.route_waypoint_radius_override = 0.8
    corridor_tactical = MovementRequest.from_passenger(passenger)
    passenger.route = []
    passenger.route_waypoint_radius_override = None
    passenger.current_goal = SimpleNamespace(kind="queue_approach")
    queue_handoff = MovementRequest.from_passenger(passenger)
    passenger.current_goal = SimpleNamespace(kind="destination")
    final = MovementRequest.from_passenger(passenger)

    assert tactical.radius == pytest.approx(0.05)
    assert body_clear_tactical.radius == pytest.approx(0.396)
    assert corridor_tactical.radius == pytest.approx(0.8)
    assert queue_handoff.radius == pytest.approx(0.05)
    assert final.radius == pytest.approx(0.45)


class _FakeSimulation:
    def __init__(self) -> None:
        self._agent = _FakeAgent(id=1, position=(0.0, 0.0))

    def agent_count(self) -> int:
        return 1

    def iterate(self) -> None:
        self._agent.position = (self._agent.position[0] + 0.01, 0.0)

    def agent(self, agent_id: int) -> _FakeAgent:
        if agent_id != self._agent.id:
            raise KeyError(agent_id)
        return self._agent

    def agents(self) -> tuple[_FakeAgent, ...]:
        return (self._agent,)


class _MissingAgentSession:
    def ensure_agent(self, **_kwargs: object) -> None:
        return None

    def iterate(self, _iterations: int, **_kwargs: object) -> None:
        return None

    def position_for(self, _passenger_id: int) -> None:
        return None

    def set_episode_id(self, _passenger_id: int, _episode_id: str) -> None:
        return None

    def removal_record_for(
        self, _passenger_id: int, *, consume: bool = False
    ) -> None:
        del consume
        return None


class _EnsureFailureSession:
    def ensure_agent(self, **_kwargs: object) -> None:
        raise RuntimeError("synthetic JuPedSim insertion failure")


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, code: str, **payload: object) -> None:
        self.events.append((code, payload))


class _RecoveringAgentSession:
    def __init__(self) -> None:
        self.ensure_count = 0
        self.iterated = False

    def ensure_agent(self, **_kwargs: object) -> None:
        self.ensure_count += 1

    def iterate(self, _iterations: int, **_kwargs: object) -> None:
        self.iterated = True

    def position_for(self, _passenger_id: int) -> tuple[float, float] | None:
        if self.iterated and self.ensure_count >= 2:
            return (0.0, 0.0)
        return None

    def remove_passenger(self, _passenger_id: int) -> None:
        return None

    def set_episode_id(self, _passenger_id: int, _episode_id: str) -> None:
        return None

    def removal_record_for(
        self, _passenger_id: int, *, consume: bool = False
    ) -> None:
        del consume
        return None


class _CompletedAgentSession(_MissingAgentSession):
    def removal_record_for(
        self, passenger_id: int, *, consume: bool = False
    ) -> JuPedSimRemovalRecord:
        del consume
        return JuPedSimRemovalRecord(
            passenger_id=passenger_id,
            reason="completed_final_waypoint",
            last_authoritative_position=(0.62, 0.0),
            reached=True,
            occurred_after_seconds=0.4,
            last_position_after_seconds=0.39,
            episode_id="7:1",
        )


class _SharedTraceSession:
    def __init__(self) -> None:
        self.positions = {1: (1.0, 0.0), 2: (0.0, 0.0)}
        self.episodes = {1: "1:1", 2: "2:1"}

    def sync_passengers(self, keep: set[int]) -> None:
        for passenger_id in set(self.positions) - keep:
            self.remove_passenger(passenger_id)

    def remove_passenger(self, passenger_id: int) -> None:
        self.positions.pop(passenger_id, None)
        self.episodes.pop(passenger_id, None)

    def ensure_agent(self, **_kwargs: object) -> None:
        return None

    def ensure_waiting_agent(
        self,
        *,
        passenger_id: int,
        position: tuple[float, float],
        **_kwargs: object,
    ) -> tuple[float, float]:
        self.positions.setdefault(passenger_id, position)
        return self.positions[passenger_id]

    def set_episode_id(self, passenger_id: int, episode_id: str) -> None:
        self.episodes[passenger_id] = episode_id

    def positions_by_passenger(self) -> dict[int, tuple[float, float]]:
        return dict(self.positions)

    def episode_ids_by_passenger(self) -> dict[int, str]:
        return dict(self.episodes)

    def iterate(
        self,
        _iterations: int,
        *,
        sample_every_nth_iteration: int | None = None,
        sample_observer=None,
    ) -> None:
        del sample_every_nth_iteration
        self.positions = {
            passenger_id: (position[0] + 0.2, position[1])
            for passenger_id, position in self.positions.items()
        }
        if sample_observer is not None:
            sample_observer(20, dict(self.positions))

    def position_for(self, passenger_id: int) -> tuple[float, float] | None:
        return self.positions.get(passenger_id)

    def removal_record_for(self, _passenger_id: int, *, consume: bool = False) -> None:
        del consume
        return None


class _ProjectedArrivalSession(_SharedTraceSession):
    def __init__(self) -> None:
        super().__init__()
        self.positions = {1: (0.0, 0.0)}
        self.episodes = {1: "1:1"}

    def iterate(self, _iterations: int, **_kwargs: object) -> None:
        self.positions[1] = (1.48, 0.0)

    def waypoint_arrival_held(self, passenger_id: int) -> bool:
        return int(passenger_id) == 1


def test_walking_session_observer_samples_internal_iterations() -> None:
    session = object.__new__(JuPedSimWalkingSession)
    session._simulation = _FakeSimulation()
    session._agent_ids = {10: 1}
    session._passenger_ids = {1: 10}
    session._agent_targets = {}
    session._agent_target_positions = {}
    session._agent_desired_speeds = {}
    session._last_positions = {}
    session._active_episode_ids = {10: "10:1"}
    session._removal_records = {}
    samples: list[tuple[int, dict[int, tuple[float, float]]]] = []

    session.iterate(
        5,
        sample_every_nth_iteration=2,
        sample_observer=lambda iteration, positions: samples.append(
            (iteration, dict(positions))
        ),
    )

    assert samples == [
        (2, {10: pytest.approx((0.02, 0.0))}),
        (4, {10: pytest.approx((0.04, 0.0))}),
    ]


def test_real_jupedsim_removal_keeps_identity_until_next_iterate() -> None:
    adapter = JuPedSimAdapter()
    if not adapter.status.available:
        pytest.skip(adapter.status.message)
    session = adapter.create_walking_session(
        width=10.0,
        height=10.0,
        walkable_area=box(0.0, 0.0, 10.0, 10.0),
        operational_model="collision_free_speed",
        agent_radius=0.18,
        target_radius=0.3,
        dt_seconds=0.01,
    )
    session.ensure_agent(
        passenger_id=7,
        position=(2.0, 2.0),
        target=(8.0, 2.0),
        desired_speed_mps=1.2,
    )
    native_id = session._agent_ids[7]

    session.remove_passenger(7)

    assert session._agent_ids == {7: native_id}
    assert session._passenger_ids == {native_id: 7}
    assert session._pending_removals == {7: native_id}
    assert session.position_for(7) == pytest.approx((2.0, 2.0))

    assert session.flush_pending_removals_if_no_active_owners()

    assert session.position_for(7) is None
    assert session._agent_ids == {}
    assert session._passenger_ids == {}
    assert session._pending_removals == {}


def test_real_jupedsim_switches_same_waypoint_when_arrival_radius_changes() -> None:
    adapter = JuPedSimAdapter()
    if not adapter.status.available:
        pytest.skip(adapter.status.message)
    session = adapter.create_walking_session(
        width=10.0,
        height=10.0,
        walkable_area=box(0.0, 0.0, 10.0, 10.0),
        operational_model="collision_free_speed",
        agent_radius=0.18,
        target_radius=0.45,
        dt_seconds=0.01,
    )
    session.ensure_agent(
        passenger_id=7,
        position=(2.0, 2.0),
        target=(8.0, 2.0),
        target_radius=0.45,
    )
    native_id = session._agent_ids[7]
    broad_stage = session._targets[(8.0, 2.0, 0.45)].stage_id

    session.ensure_agent(
        passenger_id=7,
        position=(2.0, 2.0),
        target=(8.0, 2.0),
        target_radius=0.05,
    )

    assert session._agent_ids[7] == native_id
    assert session._agent_targets[7] == (8.0, 2.0, 0.05)
    assert session._targets[(8.0, 2.0, 0.05)].stage_id != broad_stage


@pytest.mark.parametrize(
    "operational_model",
    ["collision_free_speed", "anticipation_velocity", "social_force"],
)
def test_mid_iterate_waypoint_arrival_keeps_native_identity(
    operational_model: str,
) -> None:
    adapter = JuPedSimAdapter()
    if not adapter.status.available:
        pytest.skip(adapter.status.message)
    session = adapter.create_walking_session(
        width=10.0,
        height=10.0,
        walkable_area=box(0.0, 0.0, 10.0, 10.0),
        operational_model=operational_model,
        agent_radius=0.18,
        target_radius=0.3,
        dt_seconds=0.01,
    )
    session.ensure_agent(
        passenger_id=7,
        position=(2.0, 2.0),
        target=(2.8, 2.0),
        desired_speed_mps=1.2,
    )
    native_id = session._agent_ids[7]

    session.iterate(100)

    assert session._agent_ids[7] == native_id
    assert session._passenger_ids[native_id] == 7
    assert session.agent_count == 1
    assert session._agent_targets[7][2] == -1.0
    assert session.waypoint_arrival_held(7)
    assert session._pending_removals == {}
    position = session.position_for(7)
    assert position is not None
    assert hypot(position[0] - 2.8, position[1] - 2.0) <= 0.3 + 1e-6


def test_movement_trace_recorder_is_strictly_monotonic_per_passenger() -> None:
    recorder = MovementTraceRecorder(
        sample_interval_seconds=0.2,
        integration_dt_seconds=0.01,
    )
    recorder.record_positions(
        time_seconds=0.2,
        level_id="b1",
        positions={2: (2.0, 0.0), 1: (1.0, 0.0)},
        episode_ids={1: "1:1", 2: "2:1"},
    )
    recorder.record_positions(
        time_seconds=0.2,
        level_id="b1",
        positions={1: (9.0, 9.0)},
        episode_ids={1: "1:1"},
    )
    recorder.record_positions(
        time_seconds=0.4,
        level_id="b1",
        positions={1: (1.2, 0.0)},
        episode_ids={1: "1:1"},
    )

    payload = recorder.as_dict()
    assert payload["metadata"]["every_nth_iteration"] == 20
    assert [(point["passenger_id"], point["time_seconds"]) for point in payload["points"]] == [
        (1, 0.2),
        (2, 0.2),
        (1, 0.4),
    ]
    assert [(point["episode_id"], point["sample_index"]) for point in payload["points"]] == [
        ("1:1", 0),
        ("2:1", 0),
        ("1:1", 1),
    ]


def test_simulation_trace_serializes_movement_trace_separately() -> None:
    movement_trace = {"schema_version": "movement_trace.v1", "metadata": {}, "points": []}
    trace = SimulationTrace(
        run_id="run",
        metadata={},
        snapshots=[],
        facility_events=[],
        aggregate_metrics={},
        movement_trace=movement_trace,
    ).as_dict()

    assert trace["movement_trace"] is movement_trace


def test_facility_motion_trace_uses_monotonic_indices_per_passenger() -> None:
    recorder = FacilityMotionTraceRecorder(sample_interval_seconds=0.2)

    assert recorder.sample_times(0.1, 0.61) == (0.1, 0.2, 0.4, 0.6, 0.61)
    recorder.record_positions(
        time_seconds=0.2,
        level_id="connector:elevator_a",
        phase="elevator_boarding",
        episode_id="elevator:a:1:boarding",
        positions={2: (2.0, 0.0), 1: (1.0, 0.0)},
    )
    recorder.record_positions(
        time_seconds=0.4,
        level_id="connector:elevator_a",
        phase="elevator_boarding",
        episode_id="elevator:a:1:boarding",
        positions={2: (2.2, 0.0), 1: (1.2, 0.0)},
    )

    points = recorder.as_dict()["points"]
    assert [point["sample_index"] for point in points if point["passenger_id"] == 1] == [
        0,
        1,
    ]
    assert [point["sample_index"] for point in points if point["passenger_id"] == 2] == [
        0,
        1,
    ]
    assert all(point["authority"] == "facility_process_model" for point in points)
    assert all(point["visual_only"] is False for point in points)


def test_simulation_trace_serializes_facility_motion_trace_separately() -> None:
    facility_motion_trace = {
        "schema_version": "facility_motion_trace.v1",
        "metadata": {},
        "points": [],
    }
    trace = SimulationTrace(
        run_id="run",
        metadata={},
        snapshots=[],
        facility_events=[],
        aggregate_metrics={},
        facility_motion_trace=facility_motion_trace,
    ).as_dict()

    assert trace["facility_motion_trace"] is facility_motion_trace


def test_visual_source_track_merges_five_hz_walking_truth() -> None:
    scenario = StationSandboxScenario(
        station_name="trace_visual_merge",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    frames = [
        {
            "time_seconds": time_s,
            "passengers": [
                {
                    "id": 1,
                    "x": time_s,
                    "y": 0.0,
                    "state": "entering_station",
                    "intent": "enter_and_board",
                    "goal": {"target": [1.0, 0.0]},
                }
            ],
            "metrics": {"station_persons": 1, "spawned_persons": 1},
        }
        for time_s in (0.0, 1.0)
    ]
    recorder = MovementTraceRecorder(
        sample_interval_seconds=0.2,
        integration_dt_seconds=0.01,
    )
    for sample_index in range(1, 6):
        time_s = sample_index * 0.2
        recorder.record_positions(
            time_seconds=time_s,
            level_id="ground",
            positions={1: (time_s, 0.0)},
            episode_ids={1: "1:1"},
        )

    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=[],
        movement_trace=recorder.as_dict(),
    )
    points = payload["agents"][0]["points"]

    assert [point[0] for point in points] == pytest.approx(
        [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )
    assert [point[9]["authority"] for point in points[1:-1]] == [
        "simulation_trace.movement_trace"
    ] * 4
    assert all(point[3] == pytest.approx(0.0) for point in points)
    assert (
        payload["simulation_trace"]["metadata"]["replay_fidelity"][
            "renderer_track_field"
        ]
        == "points"
    )
    assert analyze_presentation_fidelity(payload)["passed"]


def test_visual_source_track_merges_five_hz_facility_truth() -> None:
    scenario = StationSandboxScenario(
        station_name="facility_trace_visual_merge",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    frames = [
        {
            "time_seconds": time_s,
            "passengers": [
                {
                    "id": 1,
                    "x": time_s,
                    "y": 0.0,
                    "state": "riding_vertical",
                    "intent": "enter_and_board",
                    "goal": {"target": [1.0, 0.0]},
                }
            ],
            "metrics": {"station_persons": 1, "spawned_persons": 1},
        }
        for time_s in (0.0, 1.0)
    ]
    recorder = FacilityMotionTraceRecorder(sample_interval_seconds=0.2)
    for sample_index in range(1, 6):
        time_s = sample_index * 0.2
        recorder.record_positions(
            time_seconds=time_s,
            level_id="connector:elevator_a",
            phase="elevator_boarding",
            episode_id="elevator:a:1:boarding",
            positions={1: (time_s, 0.0)},
        )

    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=[],
        facility_motion_trace=recorder.as_dict(),
    )
    points = payload["agents"][0]["points"]

    assert [point[0] for point in points] == pytest.approx(
        [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )
    assert [point[9]["authority"] for point in points[1:]] == [
        "simulation_trace.facility_motion_trace"
    ] * 5
    assert analyze_presentation_fidelity(payload)["passed"]


def test_facility_boundaries_that_share_serialized_time_have_one_latest_truth() -> None:
    scenario = StationSandboxScenario(
        station_name="facility_trace_centisecond_boundary",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    frames = [
        {
            "time_seconds": time_s,
            "passengers": [
                {
                    "id": 1,
                    "x": 1.0,
                    "y": 1.0,
                    "state": "riding_vertical",
                    "intent": "enter_and_board",
                    "goal": {"target": [2.0, 1.0]},
                }
            ],
            "metrics": {"station_persons": 1, "spawned_persons": 1},
        }
        for time_s in (0.0, 1.0)
    ]
    facility_motion_trace = {
        "schema_version": "facility_motion_trace.v1",
        "metadata": {
            "authority": "facility_process_model",
            "coordinates": "station_model_meters",
            "sample_interval_seconds": 0.2,
            "visual_only": False,
            "coverage": ["elevator_unloading"],
        },
        "points": [
            {
                "passenger_id": 1,
                "time_seconds": 0.195,
                "x": 1.001,
                "y": 1.001,
                "level_id": "ground",
                "phase": "elevator_unloading",
                "episode_id": "elevator:1:unloading",
                "sample_index": 0,
            },
            {
                "passenger_id": 1,
                "time_seconds": 0.2,
                "x": 1.002,
                "y": 1.002,
                "level_id": "ground",
                "phase": "elevator_unloading",
                "episode_id": "elevator:1:unloading",
                "sample_index": 1,
            },
        ],
    }

    payload = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=[],
        facility_motion_trace=facility_motion_trace,
    )
    points = payload["agents"][0]["points"]
    serialized_boundary_points = [point for point in points if point[0] == 0.2]

    assert len(serialized_boundary_points) == 1
    assert serialized_boundary_points[0][9]["sample_index"] == 1
    assert all(
        right[0] > left[0]
        for left, right in zip(points, points[1:], strict=False)
    )
    assert analyze_presentation_fidelity(payload)["passed"]


def test_scenario_rejects_unrepresentable_movement_trace_interval() -> None:
    with pytest.raises(ValueError, match="integer multiple"):
        StationSandboxScenario(
            station_name="test",
            hour=8,
            minutes=1,
            tick_seconds=1,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="test",
            sample_hours=1,
            movement_trace_sample_seconds=0.205,
        )


def test_scenario_rejects_unknown_jupedsim_operational_model() -> None:
    with pytest.raises(ValueError, match="jupedsim_operational_model"):
        StationSandboxScenario(
            station_name="test",
            hour=8,
            minutes=1,
            tick_seconds=1,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="test",
            sample_hours=1,
            jupedsim_operational_model="teleport_model",
        )


def test_reached_jupedsim_result_preserves_authoritative_coordinate() -> None:
    scenario = StationSandboxScenario(
        station_name="no_waypoint_snap",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=4)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.set_target((5.0, 5.0))

    reached = passenger.apply_movement_result(
        MovementResult(int(passenger.unique_id), (4.7, 5.0), reached=True)
    )

    assert reached
    assert passenger.pos == pytest.approx((4.7, 5.0))


def test_physical_backend_exports_five_hz_walking_trace() -> None:
    scenario = StationSandboxScenario(
        station_name="trace_test",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=3)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )

    model.movement_backend.step_all([passenger])

    trace = model.movement_backend.movement_trace()
    assert trace["metadata"]["sample_interval_seconds"] == pytest.approx(0.2)
    assert [point["time_seconds"] for point in trace["points"]] == pytest.approx(
        [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )
    assert {point["passenger_id"] for point in trace["points"]} == {
        int(passenger.unique_id)
    }


def test_passive_layout_motion_is_committed_by_the_persistent_physical_backend() -> None:
    scenario = StationSandboxScenario(
        station_name="passive_layout_physical_authority",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=31)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.state = AgentState.WAITING_PLATFORM.value
    start = tuple(passenger.pos)
    target = model._physical_route_for_points(
        passenger,
        (model.layout_graph.geometry.paid_hall_center,),
    )[0]
    passenger.set_target(target, goal_kind="waiting", goal_label="physical slot")

    passenger.move_directly_toward_target(max_distance=1.0)

    assert passenger.pos == start
    assert passenger.passive_layout_motion_target == target
    assert passenger.passive_layout_motion_speed_mps is not None
    assert passenger.passive_layout_motion_speed_mps <= min(
        1.0,
        hypot(target[0] - start[0], target[1] - start[1]),
        scenario.jupedsim_desired_speed_mps,
    )
    model.movement_backend.step_all([passenger])
    assert passenger.pos != start
    assert int(passenger.unique_id) in model.movement_backend.active_passenger_ids()


def test_same_floor_gate_service_retains_one_native_collision_body() -> None:
    scenario = StationSandboxScenario(
        station_name="gate_service_physical_authority",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=33)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    gate = model.gates[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = gate.portal_entry_level_id
    passenger.pos = model.movement_backend.place_passenger(
        passenger,
        gate.portal_entry_position,
        target=gate.portal_entry_position,
        level_id=gate.portal_entry_level_id,
    )
    passenger_id = int(passenger.unique_id)

    assert passenger_id in model.movement_backend.active_passenger_ids()
    assert model.movement_backend.owns_continuous_facility_service_motion(
        facility_kind=gate.spec.kind,
        entry_level_id=gate.spec.entry_level_id,
        exit_level_id=gate.spec.exit_level_id,
    )
    passenger.begin_facility_service(gate.spec)

    assert passenger_id in model.movement_backend.active_passenger_ids()
    assert not model.movement_backend.owns_continuous_facility_service_motion(
        facility_kind="escalator",
        entry_level_id="b1",
        exit_level_id="b2",
    )


def test_gate_service_keeps_same_native_identity_through_finish() -> None:
    scenario = StationSandboxScenario(
        station_name="gate_service_native_identity",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=34)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    gate = model.gates[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = gate.portal_entry_level_id
    passenger.pos = model.movement_backend.place_passenger(
        passenger,
        gate.portal_entry_position,
        target=gate.portal_entry_position,
        level_id=gate.portal_entry_level_id,
    )
    model.passengers.append(passenger)
    backend = model.movement_backend
    passenger_id = int(passenger.unique_id)
    session_key = backend._session_keys_by_passenger[passenger_id]
    session = backend._sessions[session_key]
    native_id = session._agent_ids[passenger_id]

    gate._start_service(passenger, None)
    for _ in range(20):
        gate._advance_active_passes()
        assert session._agent_ids[passenger_id] == native_id
        assert passenger_id not in session._pending_removals
        if not gate.active_passes:
            break
        backend.step_all([passenger])
        model.step_index += 1

    assert not gate.active_passes
    assert backend._session_keys_by_passenger[passenger_id] == session_key
    assert session._agent_ids[passenger_id] == native_id
    assert session._passenger_ids[native_id] == passenger_id
    assert passenger_id not in session._pending_removals
    assert sum(int(agent.id) == native_id for agent in session._simulation.agents()) == 1


def test_gate_service_does_not_finish_at_semantic_destination_radius() -> None:
    scenario = StationSandboxScenario(
        station_name="gate_service_precise_native_finish",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=35)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    gate = model.gates[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = gate.portal_entry_level_id
    passenger.pos = model.movement_backend.place_passenger(
        passenger,
        gate.portal_entry_position,
        target=gate.portal_entry_position,
        level_id=gate.portal_entry_level_id,
    )
    model.passengers.append(passenger)

    gate._start_service(passenger, None)
    # Let the backend open the passive same-floor facility episode before the
    # synthetic native endpoint is committed below.
    model.movement_backend.step_all([passenger])
    active = gate.active_passes[0]
    dx = active.start_position[0] - active.end_position[0]
    dy = active.start_position[1] - active.end_position[1]
    length = hypot(dx, dy)
    semantic_radius = float(scenario.jupedsim_target_radius_units)
    passenger.pos = (
        active.end_position[0] + dx / length * semantic_radius * 0.5,
        active.end_position[1] + dy / length * semantic_radius * 0.5,
    )

    gate._advance_active_passes()

    assert gate.active_passes == [active]
    assert passenger.passive_facility_service
    assert hypot(
        passenger.pos[0] - active.end_position[0],
        passenger.pos[1] - active.end_position[1],
    ) > 0.05


def test_gate_service_finishes_at_oriented_release_plane_with_native_endpoint() -> None:
    scenario = StationSandboxScenario(
        station_name="gate_service_oriented_release_plane",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=36)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    gate = model.gates[0]
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    passenger.current_level_id = gate.portal_entry_level_id
    passenger.pos = model.movement_backend.place_passenger(
        passenger,
        gate.portal_entry_position,
        target=gate.portal_entry_position,
        level_id=gate.portal_entry_level_id,
    )
    model.passengers.append(passenger)

    gate._start_service(passenger, None)
    # Let the backend open the passive same-floor facility episode before the
    # synthetic native endpoint is committed below.
    model.movement_backend.step_all([passenger])
    active = gate.active_passes[0]
    dx = active.end_position[0] - active.start_position[0]
    dy = active.end_position[1] - active.start_position[1]
    length = hypot(dx, dy)
    native_endpoint = (
        active.end_position[0] - dy / length * 0.07,
        active.end_position[1] + dx / length * 0.07,
    )
    passenger.pos = native_endpoint

    gate._advance_active_passes()

    assert not gate.active_passes
    assert passenger.pos == pytest.approx(native_endpoint)
    event = next(
        item for item in model.facility_service_events if item.event_id == active.event_id
    )
    assert event.end_position == pytest.approx(native_endpoint)


@pytest.mark.parametrize(
    "blocker_state",
    (
        AgentState.WAITING_PLATFORM.value,
        AgentState.WALKING_TO_PLATFORM.value,
    ),
)
def test_pending_removal_completes_with_only_idle_native_blockers(
    blocker_state: str,
) -> None:
    scenario = StationSandboxScenario(
        station_name="pending_removal_idle_blocker",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="test",
        sample_hours=1,
        station_design=create_design("single_level_terminal"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    model = MetroStationModel(scenario, seed=35)
    if not model.jupedsim.status.available:
        pytest.skip(model.jupedsim.status.message)
    gate = model.gates[0]
    blocker = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    departing = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    for passenger, offset in ((blocker, -1.0), (departing, 1.0)):
        passenger.current_level_id = gate.portal_entry_level_id
        position = (
            gate.portal_entry_position[0],
            gate.portal_entry_position[1] + offset,
        )
        passenger.pos = model.movement_backend.place_passenger(
            passenger,
            position,
            target=position,
            level_id=gate.portal_entry_level_id,
        )
        passenger.target = passenger.pos
    blocker.state = blocker_state
    blocker.passive_layout_motion_step = None
    blocker.passive_layout_motion_target = None
    blocker.passive_layout_motion_speed_mps = None
    backend = model.movement_backend
    blocker_id = int(blocker.unique_id)
    departing_id = int(departing.unique_id)
    session_key = backend._session_keys_by_passenger[blocker_id]
    session = backend._sessions[session_key]
    blocker_native_id = session._agent_ids[blocker_id]

    backend.remove_passenger(departing)

    assert session._pending_removals == {
        departing_id: session._agent_ids[departing_id]
    }
    backend.step_all([blocker])

    assert departing_id not in session._agent_ids
    assert session._pending_removals == {}
    assert session._agent_ids[blocker_id] == blocker_native_id
    assert session.position_for(blocker_id) == pytest.approx(blocker.pos, abs=1e-6)


def test_identical_route_command_is_a_motion_state_noop() -> None:
    model = MetroStationModel(
        StationSandboxScenario(
            station_name="route_command_idempotence",
            hour=8,
            minutes=1,
            tick_seconds=1,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="test",
            sample_hours=1,
            station_design=create_design("single_level_terminal"),
            audit_enabled=False,
            audit_print_events=False,
        ),
        seed=32,
    )
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    route = ((10.0, 10.0), (11.0, 10.0))
    passenger.target = route[0]
    passenger.route = [route[1]]
    passenger.route_segment_start = (9.0, 10.0)
    passenger.corner_recovery_anchor = (9.5, 10.0)
    passenger.corner_recovery_speed_limit_mps = 0.4
    passenger.plan.set_goal(
        kind="goal_region",
        label="stable decision",
        target=route[0],
    )
    before = (
        passenger.target,
        tuple(passenger.route),
        passenger.route_segment_start,
        passenger.corner_recovery_anchor,
        passenger.corner_recovery_speed_limit_mps,
        passenger._pending_route_transition,
    )

    passenger.set_route(
        route,
        goal_kind="goal_region",
        goal_label="stable decision",
    )

    after = (
        passenger.target,
        tuple(passenger.route),
        passenger.route_segment_start,
        passenger.corner_recovery_anchor,
        passenger.corner_recovery_speed_limit_mps,
        passenger._pending_route_transition,
    )
    assert after == before


def test_post_control_hold_rolls_back_uncommitted_jupedsim_samples() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    recorder = MovementTraceRecorder(
        sample_interval_seconds=0.2,
        integration_dt_seconds=0.01,
        authority="jupedsim_committed_walk",
    )
    for sample_index in range(6):
        time_s = sample_index * 0.2
        recorder.record_positions(
            time_seconds=time_s,
            level_id="b1",
            positions={7: (time_s, 0.0)},
            episode_ids={7: "7:1"},
        )
    backend._movement_trace_recorder = recorder
    backend._pending_trace_commits[7] = (
        0.0,
        1.0,
        (1.0, 0.0),
        "b1",
        "7:1",
    )
    passenger = SimpleNamespace(unique_id=7)

    backend.commit_movement_result(
        passenger,
        MovementResult(7, (0.0, 0.0), reached=False),
    )

    points = backend.movement_trace()["points"]
    assert [point["time_seconds"] for point in points] == [0.0, 1.0]
    assert [(point["x"], point["y"]) for point in points] == [
        (0.0, 0.0),
        (0.0, 0.0),
    ]


def test_exact_target_passenger_switches_to_waiting_without_ghost_trace() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _SharedTraceSession()
    backend._sessions = {"b1": session}
    backend._session_keys_by_passenger = {1: "b1", 2: "b1"}
    backend._active_episode_ids = {1: "1:1", 2: "2:1"}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            movement_trace_sample_seconds=0.2,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
            walk_units_per_tick=1.0,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=True,
            jupedsim_iterations_per_tick=100,
            jupedsim_dt_seconds=0.01,
        ),
        current_time_seconds=0.0,
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    passengers = [
        SimpleNamespace(
            unique_id=1,
            state=next(iter(WALKING_STATES)),
            pos=(1.0, 0.0),
            target=(1.0, 0.0),
            current_level_id="b1",
            passive_facility_service=False,
            model=model,
        ),
        SimpleNamespace(
            unique_id=2,
            state=next(iter(WALKING_STATES)),
            pos=(0.0, 0.0),
            target=(10.0, 0.0),
            current_level_id="b1",
            passive_facility_service=False,
            model=model,
        ),
    ]

    results = backend.step_all(passengers)

    assert results[0][1].reached
    assert 1 in session.positions
    assert 1 in backend.active_passenger_ids()
    assert 1 not in backend._active_episode_ids
    assert backend._active_episode_ids[2] == "2:1"
    assert {point["passenger_id"] for point in backend.movement_trace()["points"]} == {2}


def test_projected_waypoint_arrival_completes_nominal_route_segment() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _ProjectedArrivalSession()
    backend._sessions = {"b1": session}
    backend._session_keys_by_passenger = {1: "b1"}
    backend._active_episode_ids = {1: "1:1"}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            movement_trace_sample_seconds=0.2,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
            walk_units_per_tick=1.0,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=True,
            jupedsim_iterations_per_tick=100,
            jupedsim_dt_seconds=0.01,
        ),
        current_time_seconds=0.0,
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    passenger = SimpleNamespace(
        unique_id=1,
        state=next(iter(WALKING_STATES)),
        pos=(0.0, 0.0),
        target=(1.0, 0.0),
        current_level_id="b1",
        passive_facility_service=False,
        model=model,
    )

    result = backend.step_all([passenger])[0][1]

    assert hypot(result.position[0] - passenger.target[0], 0.0) > 0.45
    assert result.reached


def test_reached_walker_is_retained_as_native_waiting_body_at_commit() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _SharedTraceSession()
    session.remove_passenger(1)
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for_position = lambda *_args, **_kwargs: "b1"
    model = SimpleNamespace()
    passenger = SimpleNamespace(
        unique_id=1,
        current_level_id="b1",
        model=model,
    )

    backend.commit_movement_result(
        passenger,
        MovementResult(1, (2.0, 3.0), reached=True),
    )

    assert session.position_for(1) == (2.0, 3.0)
    assert backend.active_passenger_ids() == {1}


def test_passive_layout_motion_is_high_rate_jupedsim_truth() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _SharedTraceSession()
    session.positions = {7: (0.0, 0.0)}
    session.episodes = {}
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        step_index=0,
        current_time_seconds=0.0,
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            movement_trace_sample_seconds=0.2,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=True,
            jupedsim_iterations_per_tick=100,
            jupedsim_dt_seconds=0.01,
        ),
        clamp_position=lambda position: position,
    )
    blocker = SimpleNamespace(
        unique_id=7,
        state=AgentState.QUEUEING_GATE.value,
        pos=(0.0, 0.0),
        target=(1.0, 0.0),
        current_level_id="b1",
        physical_motion_layer_id=None,
        passive_facility_service=False,
        passive_layout_motion_step=0,
        passive_layout_motion_target=(1.0, 0.0),
        passive_layout_motion_speed_mps=1.0,
        passive_layout_committed_delta=None,
        model=model,
    )

    assert backend.step_all([blocker]) == []

    points = backend.movement_trace()["points"]
    passive = [point for point in points if point["passenger_id"] == 7]
    assert [point["time_seconds"] for point in passive] == [0.0, 0.2]
    assert all(point["phase"] == "passive_layout" for point in passive)
    assert blocker.pos == pytest.approx((0.2, 0.0))


def test_uncommanded_passive_body_commits_native_drift_when_session_advances() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _SharedTraceSession()
    session.positions = {7: (0.0, 0.0), 8: (5.0, 0.0)}
    session.episodes = {8: "8:1"}
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        step_index=1,
        current_time_seconds=1.0,
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            movement_trace_sample_seconds=0.2,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=True,
            jupedsim_iterations_per_tick=100,
            jupedsim_dt_seconds=0.01,
        ),
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    blocker = SimpleNamespace(
        unique_id=7,
        state=AgentState.WAITING_PLATFORM.value,
        pos=(0.0, 0.0),
        target=(0.0, 0.0),
        current_level_id="b1",
        physical_motion_layer_id=None,
        passive_facility_service=False,
        passive_layout_motion_step=0,
        passive_layout_motion_target=(1.0, 0.0),
        passive_layout_motion_speed_mps=1.0,
        passive_layout_committed_delta=None,
        model=model,
    )
    walker = SimpleNamespace(
        unique_id=8,
        state=next(iter(WALKING_STATES)),
        pos=(5.0, 0.0),
        target=(10.0, 0.0),
        route=[],
        current_level_id="b1",
        physical_motion_layer_id=None,
        passive_facility_service=False,
        model=model,
    )

    backend.step_all([blocker, walker])

    assert blocker.pos == pytest.approx((0.2, 0.0))
    passive_points = [
        point
        for point in backend.movement_trace()["points"]
        if point["passenger_id"] == 7
    ]
    assert passive_points[-1]["x"] == pytest.approx(blocker.pos[0])


def test_suppressed_process_handoff_retains_body_without_dual_trace_authority() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _SharedTraceSession()
    session.positions = {7: (0.002, 0.0)}
    session.episodes = {}
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        step_index=0,
        current_time_seconds=0.0,
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            movement_trace_sample_seconds=0.2,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=True,
            jupedsim_iterations_per_tick=100,
            jupedsim_dt_seconds=0.01,
        ),
        clamp_position=lambda position: position,
    )
    blocker = SimpleNamespace(
        unique_id=7,
        state=AgentState.WALKING_TO_EXIT_GATE.value,
        pos=(0.0, 0.0),
        target=(1.0, 0.0),
        current_level_id="b1",
        physical_motion_layer_id=None,
        passive_facility_service=False,
        passive_layout_motion_step=0,
        passive_layout_motion_target=(1.0, 0.0),
        passive_layout_motion_speed_mps=1.0,
        passive_layout_committed_delta=None,
        movement_suppressed_this_step=lambda: True,
        model=model,
    )

    assert backend.step_all([blocker]) == []

    assert session.position_for(7) == (0.002, 0.0)
    assert blocker.pos == pytest.approx((0.002, 0.0))
    assert blocker.last_walk_velocity_mps == (0.0, 0.0)
    assert blocker.passive_layout_committed_delta is None
    assert backend.active_passenger_ids() == {7}
    assert backend.movement_trace()["points"] == []


@pytest.mark.parametrize("strict", [True, False])
def test_missing_jupedsim_agent_never_snaps_to_target(strict: bool) -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=strict)
    session = _MissingAgentSession()
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
            walk_units_per_tick=1.0,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=False,
            jupedsim_iterations_per_tick=1,
            jupedsim_dt_seconds=0.01,
        ),
        current_time_seconds=0.0,
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    passenger = SimpleNamespace(
        unique_id=7,
        state=next(iter(WALKING_STATES)),
        pos=(0.0, 0.0),
        target=(10.0, 0.0),
        current_level_id="b1",
        model=model,
    )

    if strict:
        with pytest.raises(RuntimeError, match="lost a tracked passenger"):
            backend._move_passengers([passenger], sync_sessions=False)
    else:
        results = backend._move_passengers([passenger], sync_sessions=False)
        assert results[0][1].position == pytest.approx(passenger.pos)
        assert results[0][1].position != passenger.target
        assert not results[0][1].reached
        assert backend.degraded_hold_count == 1
    assert backend.missing_agent_count == 1


def test_missing_jupedsim_agent_is_recovered_at_last_authoritative_position() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _RecoveringAgentSession()
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
            walk_units_per_tick=1.0,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=False,
            jupedsim_iterations_per_tick=1,
            jupedsim_dt_seconds=0.01,
        ),
        current_time_seconds=0.0,
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    passenger = SimpleNamespace(
        unique_id=7,
        state=next(iter(WALKING_STATES)),
        pos=(0.0, 0.0),
        target=(10.0, 0.0),
        current_level_id="b1",
        model=model,
    )

    results = backend._move_passengers([passenger], sync_sessions=False)

    assert results[0][1].passenger_id == 7
    assert results[0][1].position == (0.0, 0.0)
    assert not results[0][1].reached
    assert backend.missing_agent_count == 1
    assert backend.recovered_agent_count == 1


def test_non_strict_insertion_failure_holds_position_and_records_degradation() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=False)
    session = _EnsureFailureSession()
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    audit = _RecordingAudit()
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
        ),
        step_index=3,
        audit=audit,
    )
    passenger = SimpleNamespace(
        unique_id=7,
        state=next(iter(WALKING_STATES)),
        pos=(0.0, 0.0),
        target=(10.0, 0.0),
        current_level_id="b1",
        model=model,
    )

    results = backend._move_passengers([passenger], sync_sessions=False)

    assert results[0][1] == MovementResult(7, (0.0, 0.0), reached=False)
    assert backend.degraded_hold_count == 1
    assert audit.events[0][0] == "jupedsim_backend_failure_hold"
    assert audit.events[0][1]["context"]["reason"] == "ensure_agent_failed"


def test_missing_agent_near_target_is_bounded_completion_not_recovery() -> None:
    adapter = SimpleNamespace(status=SimpleNamespace(available=True, message="ok"))
    backend = JuPedSimMovementBackend(adapter, strict=True)
    session = _CompletedAgentSession()
    backend._sessions = {"b1": session}
    backend._session_for_key = lambda _model, _key: session
    backend._session_key_for = lambda _passenger: "b1"
    model = SimpleNamespace(
        scenario=SimpleNamespace(
            tick_seconds=1.0,
            jupedsim_target_radius_units=0.45,
            jupedsim_agent_radius_units=0.18,
            jupedsim_desired_speed_mps=1.2,
            walk_units_per_tick=1.0,
        ),
        simulation_clock=SimpleNamespace(
            research_valid=False,
            jupedsim_iterations_per_tick=1,
            jupedsim_dt_seconds=0.01,
        ),
        current_time_seconds=0.0,
        clamp_position=lambda position: position,
        walk_speed_factor=lambda _passenger: 1.0,
    )
    passenger = SimpleNamespace(
        unique_id=7,
        state=next(iter(WALKING_STATES)),
        pos=(0.0, 0.0),
        target=(1.0, 0.0),
        current_level_id="b1",
        model=model,
    )

    results = backend._move_passengers([passenger], sync_sessions=False)

    assert results[0][1].position == (0.62, 0.0)
    assert results[0][1].reached
    assert backend.missing_agent_count == 0
    assert backend.completed_agent_count == 1
    assert backend.recovered_agent_count == 0
