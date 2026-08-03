from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, hypot, sqrt
from typing import TYPE_CHECKING

import mesa

from .process import FacilityKind, FacilitySpec
from .runtime_base import FacilityProcessAgent
from .service_events import FacilityServiceEvent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


@dataclass
class ActiveGatePass:
    passenger: PassengerAgent
    event_id: int
    start_position: tuple[float, float]
    end_position: tuple[float, float]
    end_time: float
    total_steps: int
    progress_steps: float = 0.0
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0


class GateProcessAgent(FacilityProcessAgent):
    """Entry or exit fare-gate process."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.active_passes: list[ActiveGatePass] = []

    def _active_state(self) -> str:
        return "open"

    def _mechanical_service_entry_position(self) -> tuple[float, float]:
        return self.spec.position

    def _mechanical_service_release_position(self) -> tuple[float, float]:
        return self.spec.exit_position

    def _queue_crossing_service_entry_position(self) -> tuple[float, float]:
        return self._mechanical_service_entry_position()

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._advance_active_passes()
        self._serve_queue(train)

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return any(active.passenger is passenger for active in self.active_passes)

    def _process_interval_seconds(self) -> float:
        simulation_clock = getattr(self.model, "simulation_clock", None)
        if simulation_clock is not None:
            return float(simulation_clock.mesa_tick_seconds)
        return float(self.model.scenario.tick_seconds)

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        del train, release_count
        start_position = (float(passenger.pos[0]), float(passenger.pos[1]))
        if passenger.unique_id is None:
            raise RuntimeError("Gate service requires a stable passenger id")
        passenger_id = int(passenger.unique_id)
        passenger.begin_facility_service(self.spec)
        end_position = self._planned_gate_release_position(
            passenger,
            release_index=release_index,
        )
        distance = hypot(
            end_position[0] - start_position[0],
            end_position[1] - start_position[1],
        )
        tick_seconds = self._process_interval_seconds()
        speed_m_s = self._walking_speed_m_s()
        duration_seconds = distance / max(0.001, speed_m_s)
        total_steps = max(1, ceil(duration_seconds / tick_seconds))
        start_time = float(
            self.model.current_time_seconds + tick_seconds
        )
        end_time = start_time + duration_seconds
        transaction_seconds = (
            60.0
            * max(1, int(passenger.group_size))
            / max(0.001, float(self.effective_service_persons_per_min))
        )
        board_end_time = min(end_time, start_time + transaction_seconds)
        passenger.passive_facility_service = True
        passenger.set_target(
            end_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        event_id = self.model.next_facility_service_event_id()
        self.model.record_pending_facility_service_event(
            FacilityServiceEvent(
                event_id=event_id,
                facility_id=self.facility_id,
                facility_kind=FacilityKind.GATE.value,
                mode=self.spec.stage,
                passenger_ids=(passenger_id,),
                start_time=start_time,
                board_end_time=board_end_time,
                arrive_time=end_time,
                end_time=end_time,
                start_position=start_position,
                end_position=end_position,
                commit_time=float(self.model.current_time_seconds),
                direction=self.spec.direction,
                from_level=self.spec.entry_level_id,
                to_level=self.spec.exit_level_id,
            )
        )
        self.active_passes.append(
            ActiveGatePass(
                passenger=passenger,
                event_id=event_id,
                start_position=start_position,
                end_position=end_position,
                end_time=end_time,
                total_steps=total_steps,
                duration_seconds=duration_seconds,
                remaining_seconds=duration_seconds,
            )
        )

    def _planned_gate_release_position(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int,
    ) -> tuple[float, float]:
        forward, lateral = self._release_axes()
        spacing = self._release_spacing()
        column_order = self._release_column_order(release_index)
        row = max(0, int(release_index)) // self._release_column_count()
        candidate = (
            self.spec.exit_position[0]
            + forward[0] * row * spacing
            + lateral[0] * column_order * spacing,
            self.spec.exit_position[1]
            + forward[1] * row * spacing
            + lateral[1] * column_order * spacing,
        )
        projected = self._project_release_position(candidate)
        return self.model.movement_backend.resolve_placement(
            passenger,
            projected,
            level_id=self.spec.exit_level_id or self.spec.entry_level_id,
        )

    def _advance_active_passes(self) -> None:
        remaining: list[ActiveGatePass] = []
        completed: list[ActiveGatePass] = []
        tick_seconds = self._process_interval_seconds()
        for active in self.active_passes:
            desired_elapsed = min(
                active.duration_seconds,
                active.elapsed_seconds + tick_seconds,
            )
            desired_ratio = (
                1.0
                if active.duration_seconds <= 1e-12
                else desired_elapsed / active.duration_seconds
            )
            desired_position = (
                active.start_position[0]
                + (active.end_position[0] - active.start_position[0]) * desired_ratio,
                active.start_position[1]
                + (active.end_position[1] - active.start_position[1]) * desired_ratio,
            )
            movement_fraction = self._gate_backpressure_fraction(
                active.passenger,
                active.passenger.pos,
                desired_position,
            )
            elapsed_advance = (desired_elapsed - active.elapsed_seconds) * movement_fraction
            active.elapsed_seconds += elapsed_advance
            active.remaining_seconds = max(
                0.0,
                active.duration_seconds - active.elapsed_seconds,
            )
            blocked_seconds = (
                max(0.0, tick_seconds - elapsed_advance)
                if active.remaining_seconds > 1e-9
                else 0.0
            )
            if blocked_seconds > 1e-9:
                self._delay_gate_event(active, blocked_seconds)
            active.progress_steps = (
                float(active.total_steps)
                if active.duration_seconds <= 1e-12
                else active.total_steps
                * active.elapsed_seconds
                / active.duration_seconds
            )
            ratio = (
                1.0
                if active.duration_seconds <= 1e-12
                else active.elapsed_seconds / active.duration_seconds
            )
            active.passenger.pos = self.model.clamp_position(
                (
                    active.start_position[0]
                    + (active.end_position[0] - active.start_position[0]) * ratio,
                    active.start_position[1]
                    + (active.end_position[1] - active.start_position[1]) * ratio,
                )
            )
            if active.remaining_seconds <= 1e-9:
                completed.append(active)
            else:
                remaining.append(active)
        for active in completed:
            self._finish_gate_pass(active)
        self.active_passes = remaining

    def _gate_backpressure_fraction(
        self,
        passenger: PassengerAgent,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        """Return the body-clear fraction of one proposed in-lane advance."""

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = hypot(dx, dy)
        if distance <= 1e-12:
            return 1.0
        ux = dx / distance
        uy = dy / distance
        minimum_distance = self._release_min_distance()
        level_id = self.spec.exit_level_id or self.spec.entry_level_id
        allowed_distance = distance
        for other in self.model.passengers:
            if other is passenger or other.current_level_id != level_id:
                continue
            offset_x = other.pos[0] - start[0]
            offset_y = other.pos[1] - start[1]
            longitudinal = offset_x * ux + offset_y * uy
            if longitudinal <= 1e-9:
                continue
            lateral = abs(offset_x * uy - offset_y * ux)
            if lateral >= minimum_distance - 1e-9:
                continue
            clearance_along_path = sqrt(
                max(0.0, minimum_distance**2 - lateral**2)
            )
            allowed_distance = min(
                allowed_distance,
                max(0.0, longitudinal - clearance_along_path),
            )
        return max(0.0, min(1.0, allowed_distance / distance))

    def _delay_gate_event(self, active: ActiveGatePass, delay_seconds: float) -> None:
        if delay_seconds <= 0.0:
            return
        active.end_time += delay_seconds
        for index, event in enumerate(self.model.facility_service_events):
            if event.event_id != active.event_id:
                continue
            self.model.facility_service_events[index] = replace(
                event,
                end_time=event.end_time + delay_seconds,
                arrive_time=(
                    None
                    if event.arrive_time is None
                    else event.arrive_time + delay_seconds
                ),
            )
            return

    def _finish_gate_pass(self, active: ActiveGatePass) -> None:
        passenger = active.passenger
        passenger.passive_facility_service = False
        passenger.pos = self.model.clamp_position(active.end_position)
        passenger.suppress_movement_for_current_step()
        passenger.advance_after_movement(True)
        self.served_persons += passenger.group_size
        if passenger.unique_id is None:
            raise RuntimeError("Gate service completion requires a stable passenger id")
        self.model.observe_facility_service_completed(
            self.facility_id,
            (int(passenger.unique_id),),
            active.end_time,
        )
        # Service completion changes the Goal Graph immediately.  Apply the
        # resulting physical command in the same facility phase so a final-tick
        # completion cannot leave graph=done while the passenger still exposes
        # ``being_served`` in the authoritative snapshot.
        self.model.goal_coordinator.poll(passenger)

    def finalize(self) -> None:
        """Preserve in-flight passes at a truncated simulation horizon."""
