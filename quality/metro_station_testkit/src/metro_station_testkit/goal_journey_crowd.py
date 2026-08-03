"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metro_station.adapters.simulation.movement.backend import MovementResult
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_journey_fixture import CONCOURSE_LEVEL, PLATFORM_LEVEL
from .goal_journey_passenger import GoalJourneyPassenger

if TYPE_CHECKING:
    from .goal_journey_micro_scene import GoalJourneyMicroScene


@dataclass(frozen=True)
class CrowdLoop:
    start: tuple[float, float]
    level_id: str
    waypoints: tuple[tuple[float, float], ...]


class GoalJourneyCrowdPassenger(GoalJourneyPassenger):
    def __init__(
        self,
        model: GoalJourneyMicroScene,
        *,
        unique_id: int,
        loop: CrowdLoop,
    ) -> None:
        super().__init__(
            model,
            unique_id=unique_id,
            position=loop.start,
            level_id=loop.level_id,
        )
        self.intent = "background_crowd"
        self.state = (
            AgentState.WALKING_TO_PLATFORM.value
            if loop.level_id == PLATFORM_LEVEL
            else AgentState.ENTERING_STATION.value
        )
        self._waypoints = loop.waypoints
        self._waypoint_index = 0
        self.set_target(self._waypoints[0], goal_kind="crowd_flow", goal_label="background")

    def apply_movement_result(self, result: MovementResult) -> bool:
        reached = super().apply_movement_result(result)
        if not reached:
            return False
        self._waypoint_index = (self._waypoint_index + 1) % len(self._waypoints)
        self.set_target(
            self._waypoints[self._waypoint_index],
            goal_kind="crowd_flow",
            goal_label="background",
        )
        return False


def populate_journey_crowd(scene: GoalJourneyMicroScene) -> None:
    loops = (
        *_segment_loops(CONCOURSE_LEVEL, 24, 2.8, 9.0, (3.1, 4.4, 9.6)),
        *_segment_loops(CONCOURSE_LEVEL, 28, 20.0, 28.0, (3.0, 4.4, 9.6, 11.0)),
        *_segment_loops(PLATFORM_LEVEL, 40, 43.0, 54.0, (3.2, 5.2, 8.8, 10.8)),
    )
    for loop in loops:
        passenger = GoalJourneyCrowdPassenger(
            scene,
            unique_id=scene.allocate_passenger_id(),
            loop=loop,
        )
        scene.crowd.append(passenger)
        scene.passengers.append(passenger)


def _segment_loops(
    level_id: str,
    count: int,
    x_start: float,
    x_end: float,
    lanes: tuple[float, ...],
) -> tuple[CrowdLoop, ...]:
    columns = (count + len(lanes) - 1) // len(lanes)
    spacing = (x_end - x_start) / max(1, columns - 1)
    loops = []
    for index in range(count):
        column = index % columns
        lane = lanes[(index // columns) % len(lanes)]
        start = (x_start + column * spacing, lane)
        destination = (x_end if index % 2 == 0 else x_start, lane)
        opposite = (x_start if destination[0] == x_end else x_end, lane)
        loops.append(CrowdLoop(start=start, level_id=level_id, waypoints=(destination, opposite)))
    return tuple(loops)
