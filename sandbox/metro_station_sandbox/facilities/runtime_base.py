from __future__ import annotations

from abc import abstractmethod
from math import hypot
from typing import TYPE_CHECKING

import mesa

from ..agents.base import ServiceAgent
from ..planning.plan import AgentState
from ..station.geometry import project_to_safe_point
from .process import FacilityKind, FacilitySpec
from .service_events import FacilityServiceEvent

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class FacilityProcessAgent(ServiceAgent):
    """Abstract queue/service/release process for a station facility."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model)
        self.spec = spec
        self.facility_id = spec.facility_id
        self.state = self._initial_state()
        self.queue: list[PassengerAgent] = []
        self.service_credit = 0.0
        self.served_persons = 0
        self._service_release_positions_this_tick: list[tuple[float, float]] = []

    @property
    def queue_persons(self) -> int:
        return sum(passenger.group_size for passenger in self.queue)

    @property
    def is_open(self) -> bool:
        return self.state in {"open", "running"}

    @property
    def is_running(self) -> bool:
        return self.is_open

    @property
    def is_available_for_choice(self) -> bool:
        return self.is_open

    @property
    def effective_service_persons_per_min(self) -> float:
        return float(self.spec.service_persons_per_min)

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return False

    def join_queue(self, passenger: PassengerAgent) -> None:
        passenger.enter_facility_queue(self.spec)
        if passenger not in self.queue:
            self.queue.append(passenger)

    def step(self, train: TrainAgent | None = None) -> None:
        self._sync_state(train)
        self._layout_queue()
        self._serve_queue(train)

    def _initial_state(self) -> str:
        return self._active_state()

    @abstractmethod
    def _active_state(self) -> str:
        """State used when the facility can accept service."""

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = self._active_state()

    def _layout_queue(self) -> None:
        speed = self._queue_layout_speed_units_per_tick()
        for index, passenger in enumerate(self.queue):
            passenger.set_target(
                self.spec.queue_layout.slot(index),
                goal_kind="queued",
                goal_label=f"{self.spec.label} queue slot",
                facility_id=self.spec.facility_id,
                stage=self.spec.stage,
            )
            passenger.move_directly_toward_target(speed)

    def _queue_layout_speed_units_per_tick(self) -> float:
        return max(0.1, float(self.model.scenario.walk_units_per_tick))

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open:
            return

        self.service_credit += self._service_groups_per_tick()
        release_count = min(len(self.queue), int(self.service_credit))
        release_index = 0
        self._service_release_positions_this_tick = []
        while self.queue and self.service_credit >= 1.0:
            passenger = self.queue[0]
            if not self._can_start_service(
                passenger,
                train,
                release_index=release_index,
                release_count=max(1, release_count),
            ):
                break
            passenger = self.queue.pop(0)
            try:
                self._start_service(
                    passenger,
                    train,
                    release_index=release_index,
                    release_count=max(1, release_count),
                )
            except RuntimeError:
                passenger.enter_facility_queue(self.spec)
                self.queue.insert(0, passenger)
                break
            self.service_credit -= 1.0
            release_index += 1

    def _service_groups_per_tick(self) -> float:
        scenario = self.model.scenario
        group_size = max(1, int(scenario.group_size))
        return (
            self.effective_service_persons_per_min
            / group_size
            * scenario.tick_seconds
            / 60.0
        )

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        return self._passenger_ready_for_service(passenger, release_index=release_index)

    def _passenger_ready_for_service(
        self,
        passenger: PassengerAgent,
        *,
        release_index: int = 0,
    ) -> bool:
        target = self.spec.queue_layout.slot(max(0, int(release_index)))
        distance = hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1])
        return distance <= self._service_ready_radius()

    def _service_ready_radius(self) -> float:
        scenario = self.model.scenario
        return max(
            float(scenario.jupedsim_target_radius_units),
            float(getattr(scenario, "personal_space_units", 0.8)) * 0.35,
        )

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = False
        self.served_persons += passenger.group_size


class GateProcessAgent(FacilityProcessAgent):
    """Entry or exit fare-gate process."""

    def _active_state(self) -> str:
        return "open"

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        start_time, board_end_time, end_time = self._service_window_times(
            release_index,
            release_count,
            passenger.group_size,
        )
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = True
        release_position = self._release_position(passenger, release_index)
        passenger.set_target(
            release_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        passenger.pos = release_position
        passenger.passive_facility_service = False
        self.served_persons += passenger.group_size
        self.model.record_facility_service_event(
            FacilityServiceEvent(
                event_id=self.model.next_facility_service_event_id(),
                facility_id=self.facility_id,
                facility_kind=FacilityKind.GATE.value,
                mode=self.spec.stage,
                passenger_ids=(int(passenger.unique_id),),
                start_time=start_time,
                board_end_time=board_end_time,
                arrive_time=end_time,
                end_time=end_time,
                start_position=self.spec.position,
                end_position=release_position,
                direction=self.spec.direction,
                from_level=self.spec.entry_level_id,
                to_level=self.spec.exit_level_id,
            )
        )
        passenger.advance_after_movement(True)

    def _service_window_times(
        self,
        release_index: int,
        release_count: int,
        group_size: int,
    ) -> tuple[float, float, float]:
        scenario = self.model.scenario
        window_end = float(self.model.current_time_seconds)
        window_start = max(0.0, window_end - float(scenario.tick_seconds))
        slot_count = max(1, int(release_count))
        slot_time = window_start + (window_end - window_start) * (
            (max(0, int(release_index)) + 1) / (slot_count + 1)
        )
        service_seconds = 60.0 * max(1, int(group_size)) / max(
            0.001,
            float(self.effective_service_persons_per_min),
        )
        slot_span = (window_end - window_start) / (slot_count + 1)
        duration = max(0.05, min(service_seconds, slot_span * 0.9))
        start_time = max(window_start, slot_time - duration)
        board_end_time = start_time + (slot_time - start_time) * 0.55
        return start_time, board_end_time, slot_time

    def _release_position(
        self,
        passenger: PassengerAgent,
        release_index: int,
    ) -> tuple[float, float]:
        base = self.spec.exit_position
        forward, lateral = self._release_axes()
        spacing = self._release_spacing()
        column_order = (0, -1, 1)[release_index % 3]
        row = release_index // 3
        candidates = self._release_candidates(base, forward, lateral, spacing, column_order, row)
        min_distance = self._release_min_distance()
        for candidate in candidates:
            projected = self._project_release_position(candidate)
            if not self._has_release_clearance(projected, min_distance):
                continue
            try:
                release_position = self.model.movement_backend.place_passenger(
                    passenger,
                    projected,
                    target=projected,
                    level_id=self.spec.exit_level_id or self.spec.entry_level_id,
                )
            except Exception:
                continue
            if self._has_release_clearance(release_position, min_distance):
                self._service_release_positions_this_tick.append(release_position)
                return release_position

        raise RuntimeError(f"No release placement available for {self.facility_id}")

    def _release_axes(self) -> tuple[tuple[float, float], tuple[float, float]]:
        sx, sy = self.spec.position
        ex, ey = self.spec.exit_position
        dx = ex - sx
        dy = ey - sy
        length = hypot(dx, dy)
        if length <= 0.001:
            qx, qy = self.spec.queue_anchor
            dx = ex - qx
            dy = ey - qy
            length = hypot(dx, dy)
        if length <= 0.001:
            return (1.0, 0.0), (0.0, 1.0)
        forward = (dx / length, dy / length)
        lateral = (-forward[1], forward[0])
        return forward, lateral

    def _release_spacing(self) -> float:
        scenario = self.model.scenario
        clearance = self._release_min_distance() + 0.04
        personal = float(getattr(scenario, "personal_space_units", 0.8)) * 0.55
        return max(0.42, min(0.7, max(clearance, personal)))

    def _release_min_distance(self) -> float:
        scenario = self.model.scenario
        return max(
            0.05,
            float(scenario.jupedsim_agent_radius_units)
            * float(scenario.jupedsim_clearance_multiplier),
        )

    def _release_candidates(
        self,
        base: tuple[float, float],
        forward: tuple[float, float],
        lateral: tuple[float, float],
        spacing: float,
        column_order: int,
        row: int,
    ) -> list[tuple[float, float]]:
        lateral_orders = [column_order]
        if column_order != 0:
            lateral_orders.append(column_order * 2)
        lateral_orders.extend([0, -1, 1, -2, 2, -3, 3])
        forward_steps = [
            row,
            row + 1,
            max(0, row - 1),
            row + 2,
            row + 3,
            row + 4,
            row + 5,
        ]
        candidates: list[tuple[float, float]] = []
        seen: set[tuple[int, int]] = set()
        for forward_step in forward_steps:
            for lateral_order in lateral_orders:
                key = (forward_step, lateral_order)
                if key in seen:
                    continue
                seen.add(key)
                forward_offset = forward_step * spacing
                lateral_offset = lateral_order * spacing
                candidates.append(
                    (
                        base[0] + forward[0] * forward_offset + lateral[0] * lateral_offset,
                        base[1] + forward[1] * forward_offset + lateral[1] * lateral_offset,
                    )
                )
        return candidates

    def _project_release_position(self, position: tuple[float, float]) -> tuple[float, float]:
        candidate = self.model.clamp_position(position)
        level_id = self.spec.exit_level_id or self.spec.entry_level_id
        try:
            area = self.model.jupedsim_walkable_area(level_id)
            return project_to_safe_point(
                area,
                candidate,
                clearance=max(0.02, self.model.scenario.jupedsim_agent_radius_units * 1.05),
                require_inside=False,
            )
        except Exception:
            return candidate

    def _has_release_clearance(
        self,
        candidate: tuple[float, float],
        min_distance: float,
    ) -> bool:
        for existing in self._service_release_positions_this_tick:
            if hypot(candidate[0] - existing[0], candidate[1] - existing[1]) < min_distance:
                return False
        return True


class BoardingDoorProcessAgent(FacilityProcessAgent):
    """Train-door process gated by train dwell and remaining capacity."""

    def _initial_state(self) -> str:
        return "closed"

    def _active_state(self) -> str:
        return "open"

    def _sync_state(self, train: TrainAgent | None = None) -> None:
        self.state = "open" if train is not None and train.is_boarding else "closed"

    def _can_start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> bool:
        return (
            super()._can_start_service(
                passenger,
                train,
                release_index=release_index,
                release_count=release_count,
            )
            and train is not None
            and train.capacity_remaining >= passenger.group_size
        )

    def _start_service(
        self,
        passenger: PassengerAgent,
        train: TrainAgent | None,
        *,
        release_index: int = 0,
        release_count: int = 1,
    ) -> None:
        if train is None:
            return
        train.current_load_persons += passenger.group_size
        passenger.begin_facility_service(self.spec)
        passenger.passive_facility_service = False
        passenger.advance_after_movement(True)
        if passenger.state != AgentState.DEPARTED.value:
            self.model.complete_departure(passenger, boarded=True)
        self.served_persons += passenger.group_size
