"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metro_station.adapters.simulation.facilities.process import FacilitySpec
from .goal_gate_micro_passenger import GoalGateMicroPassenger

if TYPE_CHECKING:
    from .goal_stairs_micro_scene import GoalStairsMicroScene


class GoalStairsMicroPassenger(GoalGateMicroPassenger):
    """Passenger contract for real StairsProcessAgent and JuPedSim execution."""

    def __init__(
        self,
        model: GoalStairsMicroScene,
        *,
        unique_id: int,
        position: tuple[float, float],
        level_id: str,
        blocker: bool = False,
    ) -> None:
        super().__init__(
            model,
            unique_id=unique_id,
            position=position,
            blocker=blocker,
        )
        self.intent = "vertical_transfer_goal_probe"
        self.current_level_id = level_id

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        super().enter_facility_queue(spec)
        if spec.entry_level_id is not None:
            self.current_level_id = spec.entry_level_id

    def begin_facility_service(self, spec: FacilitySpec) -> None:
        super().begin_facility_service(spec)
        if spec.exit_level_id is not None:
            self.current_level_id = spec.exit_level_id
