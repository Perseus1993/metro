from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from metro_station.adapters.simulation.movement.jps_adapter import (
    JuPedSimRemovalRecord,
    JuPedSimWalkingSession,
)
from metro_station.adapters.simulation.movement.backend import (
    JuPedSimMovementBackend,
    MovementResult,
)
from metro_station.adapters.simulation.movement.trajectory_trace import MovementTraceRecorder
from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.planning.plan import AgentIntent
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


def test_exact_target_passenger_leaves_shared_session_before_trace_iteration() -> None:
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
    assert 1 not in session.positions
    assert 1 not in backend.active_passenger_ids()
    assert {point["passenger_id"] for point in backend.movement_trace()["points"]} == {2}


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
