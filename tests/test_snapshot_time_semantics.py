from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from math import hypot

import pytest

from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.movement.backend import MovementBackend, MovementResult
from metro_station.adapters.simulation.planning.plan import AgentIntent
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


class SmallStepMovementBackend(MovementBackend):
    """Keep passengers active while making adjacent samples observably different."""

    def move(self, passenger) -> MovementResult:
        x, y = passenger.pos
        target_x, target_y = passenger.target
        distance = hypot(target_x - x, target_y - y)
        if distance <= 0.001:
            return MovementResult(int(passenger.unique_id), passenger.pos, reached=False)
        step = min(0.1, distance / 2.0)
        ratio = step / distance
        return MovementResult(
            int(passenger.unique_id),
            (x + (target_x - x) * ratio, y + (target_y - y) * ratio),
            reached=False,
        )


def _scenario() -> StationSandboxScenario:
    return replace(
        StationSandboxScenario(
            station_name="snapshot-time-semantics",
            hour=8,
            minutes=1,
            tick_seconds=1,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="unit_test",
            sample_hours=1,
            station_design=create_design("single_level_terminal"),
            goal_graph_mode="active",
            audit_enabled=False,
            audit_print_events=False,
        ),
        train_headway_seconds=600,
    )


def test_spawn_and_post_step_frames_have_strict_boundary_times() -> None:
    model = MetroStationModel(
        _scenario(),
        seed=202,
        movement_backend=SmallStepMovementBackend(),
    )
    model.spawn_schedule.clear()
    model.spawn_schedule.update(
        {
            0: Counter({AgentIntent.ENTER_AND_BOARD.value: 1}),
            2: Counter({AgentIntent.ENTER_AND_BOARD.value: 1}),
        }
    )

    for _ in range(4):
        model.step()

    assert [(frame["step"], frame["time_seconds"]) for frame in model.frames] == [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
    ]
    assert all(
        frame["time_seconds"] == frame["step"] * model.scenario.tick_seconds
        for frame in model.frames
    )

    observations: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    for frame in model.frames:
        for passenger in frame["passengers"]:
            observations[int(passenger["id"])].append(
                (float(frame["time_seconds"]), float(passenger["x"]), float(passenger["y"]))
            )

    assert len(observations) == 2
    for samples in observations.values():
        times = [time_seconds for time_seconds, _x, _y in samples]
        assert all(later > earlier for earlier, later in zip(times, times[1:], strict=False))
        assert len(times) == len(set(times))

    first_samples = sorted(samples[0][0] for samples in observations.values())
    assert first_samples == [0.0, 2.0]
    first_passenger_samples = min(observations.values(), key=lambda samples: samples[0][0])
    assert first_passenger_samples[0][1:] != first_passenger_samples[1][1:]


def test_repeated_spawn_capture_refreshes_one_boundary_frame() -> None:
    model = MetroStationModel(
        _scenario(),
        seed=203,
        movement_backend=SmallStepMovementBackend(),
    )
    model.spawn_schedule.clear()
    model.step()
    passenger = model._spawn_passenger(AgentIntent.ENTER_AND_BOARD)

    model._capture_spawn_evidence_frame()
    model._spawned_since_last_frame = True
    model._capture_spawn_evidence_frame()

    assert len(model.frames) == 1
    assert model.frames[0]["step"] == 1
    assert model.frames[0]["time_seconds"] == 1
    assert [item["id"] for item in model.frames[0]["passengers"]] == [passenger.unique_id]


@pytest.mark.parametrize("passenger_count", (50, 100))
def test_bulk_launch_has_one_strictly_increasing_track_per_passenger(
    passenger_count: int,
) -> None:
    model = MetroStationModel(
        _scenario(),
        seed=204,
        movement_backend=SmallStepMovementBackend(),
    )
    model.spawn_schedule.clear()
    launch_certificate = next(
        item
        for item in model.layout_graph.spatial_capacity_certificates
        if item.resource_kind == "platform_waiting"
    )
    assert launch_certificate.certified_body_capacity >= passenger_count
    # This is a timestamp stress injection, not production ingress demand.
    # Use distinct compiler-certified cells so the test can launch a large
    # cohort at one boundary without bypassing the physical non-overlap
    # invariant of the finite entrance spawn reservoir.
    for position in launch_certificate.slots[:passenger_count]:
        model._spawn_passenger(
            AgentIntent.ENTER_AND_BOARD,
            initial_position=position,
            initial_level_id=launch_certificate.level_id,
        )

    model.step()

    observations: dict[int, list[float]] = defaultdict(list)
    for frame in model.frames:
        for passenger in frame["passengers"]:
            observations[int(passenger["id"])].append(float(frame["time_seconds"]))

    assert len(observations) == passenger_count
    assert all(times == [0.0, 1.0] for times in observations.values())
    assert sum(len(times) - len(set(times)) for times in observations.values()) == 0
