"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from math import hypot

from metro_station.adapters.simulation.facilities.process import FacilitySpec
from metro_station.adapters.simulation.movement.backend import MovementResult
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage

if TYPE_CHECKING:
    from .goal_gate_micro_scene import GoalGateMicroScene


class GoalGateMicroPassenger:
    """Minimal passenger contract shared by JuPedSim and GateProcessAgent."""

    def __init__(
        self,
        model: GoalGateMicroScene,
        *,
        unique_id: int,
        position: tuple[float, float],
        blocker: bool = False,
    ) -> None:
        self.model = model
        self.unique_id = unique_id
        self.group_size = 1
        self.intent = "entry_gate_goal_probe"
        self.state = AgentState.ENTERING_STATION.value
        self.pos = model.clamp_position(position)
        self.target = self.pos
        self.current_level_id = "concourse"
        self.assigned_facility_id: str | None = None
        self.passive_facility_service = False
        self.suppress_movement_step: int | None = None
        self.blocker = blocker
        self.goal: dict[str, Any] = {
            "kind": "hold" if blocker else "source",
            "label": "crowd blocker" if blocker else "source",
            "target": self.target,
            "facility_id": None,
            "stage": None,
        }

    def set_target(
        self,
        target: tuple[float, float],
        *,
        goal_kind: str = "walk",
        goal_label: str = "target",
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        self.target = self.model.clamp_position(target)
        self.goal = {
            "kind": goal_kind,
            "label": goal_label,
            "target": self.target,
            "facility_id": facility_id,
            "stage": stage.value if isinstance(stage, FacilityStage) else stage,
        }

    def apply_movement_result(self, result: MovementResult) -> bool:
        self.pos = self.model.clamp_position(result.position)
        return bool(result.reached)

    def move_directly_toward_target(
        self,
        max_distance: float | None = None,
        *,
        occupied_positions=(),
        min_clearance: float | None = None,
    ) -> bool:
        del occupied_positions, min_clearance
        distance = hypot(self.target[0] - self.pos[0], self.target[1] - self.pos[1])
        step = self.model.scenario.walk_units_per_tick if max_distance is None else max_distance
        if distance <= max(0.001, step):
            self.pos = self.target
            return True
        ratio = step / distance
        self.pos = self.model.clamp_position(
            (
                self.pos[0] + (self.target[0] - self.pos[0]) * ratio,
                self.pos[1] + (self.target[1] - self.pos[1]) * ratio,
            )
        )
        return False

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        self.model.movement_backend.remove_passenger(self)
        self.state = spec.queue_state
        self.assigned_facility_id = spec.facility_id
        self.set_target(
            spec.queue_anchor,
            goal_kind="queued",
            goal_label=f"{spec.label} queue",
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def begin_facility_service(self, spec: FacilitySpec) -> None:
        self.model.movement_backend.remove_passenger(self)
        self.state = spec.service_state
        self.assigned_facility_id = spec.facility_id
        self.set_target(
            spec.exit_position,
            goal_kind="being_served",
            goal_label=spec.label,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def suppress_movement_for_current_step(self) -> None:
        self.suppress_movement_step = self.model.step_index

    def movement_suppressed_this_step(self) -> bool:
        return self.suppress_movement_step == self.model.step_index

    def advance_after_movement(self, reached: bool) -> None:
        del reached

    def remove(self) -> None:
        return None
