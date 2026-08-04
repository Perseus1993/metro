"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from math import hypot

from metro_station.adapters.simulation.facilities.process import FacilitySpec
from metro_station.adapters.simulation.movement.backend import MovementResult
from metro_station.adapters.simulation.movement.passive_motion_speed import (
    bounded_passive_speed_mps,
)
from metro_station.adapters.simulation.movement.cornering_speed import (
    transition_speed_limit_mps,
)
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
        self.passive_layout_motion_step: int | None = None
        self.passive_layout_motion_target: tuple[float, float] | None = None
        self.passive_layout_motion_speed_mps: float | None = None
        self.last_walk_velocity_mps = (0.0, 0.0)
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
        tick_seconds = max(1e-9, float(self.model.scenario.tick_seconds))
        self.last_walk_velocity_mps = (
            (float(result.position[0]) - float(self.pos[0])) / tick_seconds,
            (float(result.position[1]) - float(self.pos[1])) / tick_seconds,
        )
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
        backend = self.model.movement_backend
        owns_passive_motion = getattr(backend, "owns_passive_layout_motion", None)
        if callable(owns_passive_motion) and owns_passive_motion():
            tick_seconds = max(1e-9, float(self.model.scenario.tick_seconds))
            self.request_passive_layout_motion(
                tuple(self.target),
                requested_speed_mps=min(1.2, float(step) / tick_seconds),
            )
            return False
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

    def request_passive_layout_motion(
        self,
        target: tuple[float, float],
        *,
        requested_speed_mps: float,
    ) -> None:
        """Implement the production passenger's passive-motion protocol."""

        scenario = self.model.scenario
        tick_seconds = max(1e-9, float(scenario.tick_seconds))
        observation_seconds = float(
            getattr(scenario, "movement_trace_sample_seconds", tick_seconds)
        )
        target = (float(target[0]), float(target[1]))
        desired_speed = min(
            float(getattr(scenario, "jupedsim_desired_speed_mps", 1.2)),
            float(requested_speed_mps),
        )
        transition_limit = transition_speed_limit_mps(
            tuple(float(value) for value in self.last_walk_velocity_mps),
            (target[0] - self.pos[0], target[1] - self.pos[1]),
            desired_speed,
            scenario,
            acceleration_window_s=observation_seconds,
        )
        current_speed = hypot(*self.last_walk_velocity_mps)
        acceleration_limit = float(
            getattr(scenario, "cornering_acceleration_limit_m_s2", 3.2)
        )
        published_target = target
        if transition_limit is None and current_speed > 1e-9:
            direction_bounded_speed = 0.001
            published_target = (float(self.pos[0]), float(self.pos[1]))
        else:
            direction_bounded_speed = (
                0.001 if transition_limit is None else transition_limit
            )
        self.passive_layout_motion_step = int(self.model.step_index)
        self.passive_layout_motion_target = published_target
        scalar_bounded_speed = bounded_passive_speed_mps(
            distance_m=hypot(
                published_target[0] - self.pos[0],
                published_target[1] - self.pos[1],
            ),
            requested_speed_mps=direction_bounded_speed,
            current_speed_mps=hypot(*self.last_walk_velocity_mps),
            control_interval_s=tick_seconds,
            observation_interval_s=observation_seconds,
            acceleration_limit_m_s2=acceleration_limit,
        )
        self.passive_layout_motion_speed_mps = min(
            scalar_bounded_speed,
            direction_bounded_speed,
        )

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
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
        self.passive_layout_motion_step = None
        self.passive_layout_motion_target = None
        self.passive_layout_motion_speed_mps = None
        owns_service_motion = getattr(
            self.model.movement_backend,
            "owns_continuous_facility_service_motion",
            None,
        )
        retained_by_backend = bool(
            callable(owns_service_motion)
            and owns_service_motion(
                facility_kind=str(spec.kind),
                entry_level_id=spec.entry_level_id,
                exit_level_id=spec.exit_level_id,
            )
        )
        if not retained_by_backend:
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
