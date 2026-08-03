"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_boarding_fixture import PLATFORM_LEVEL
from .goal_gate_micro_passenger import GoalGateMicroPassenger

if TYPE_CHECKING:
    from .goal_boarding_micro_scene import GoalBoardingMicroScene


class GoalBoardingMicroPassenger(GoalGateMicroPassenger):
    def __init__(
        self,
        model: GoalBoardingMicroScene,
        *,
        unique_id: int,
        position: tuple[float, float],
        blocker: bool = False,
    ) -> None:
        super().__init__(
            model,
            unique_id=unique_id,
            position=position,
            blocker=blocker,
        )
        self.intent = "platform_boarding_goal_probe"
        self.state = AgentState.WALKING_TO_PLATFORM.value
        self.current_level_id = PLATFORM_LEVEL
