from __future__ import annotations

from abc import abstractmethod
from math import hypot
from typing import TYPE_CHECKING

import mesa

from ..movement.backend import MovementResult
from ..movement.dynamic_body_clearance import external_body_positions
from ..station.geometry import project_to_safe_point
from .base import FacilityAgent
from .facility_queue import FacilityQueue
from .process import FacilitySpec

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.transit import TrainAgent


class FacilityProcessAgent(FacilityAgent):
    """Abstract queue/service/release process for a station facility."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.state = self._initial_state()
        queue_capacity = (
            len(spec.queue_layout.slots)
            if spec.queue_layout.slots
            else max(1, int(spec.fallback_queue_capacity))
        )
        self.queue = FacilityQueue(
            spec.queue_layout,
            max_length=queue_capacity,
        )
        self.service_credit = 0.0
        self.served_persons = 0
        self._service_release_positions_this_tick: list[tuple[float, float]] = []

    @property
    def queue_persons(self) -> int:
        return self.queue.persons

    @property
    def is_open(self) -> bool:
        return not self.is_forced_disabled and self.state in {"open", "running"}

    @property
    def is_running(self) -> bool:
        return self.is_open

    @property
    def is_available_for_choice(self) -> bool:
        return self.is_open and not self.queue.is_full

    @property
    def is_available_for_queue(self) -> bool:
        return self.is_open and not self.queue.is_full

    @property
    def effective_service_persons_per_min(self) -> float:
        return float(self.spec.service_persons_per_min)

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return False

    def join_queue(
        self,
        passenger: PassengerAgent,
        *,
        authority: str | None = None,
        settle_after_walking: bool = False,
        preferred_slot_index: int | None = None,
    ) -> bool:
        if not self._queue_authorized(passenger, authority):
            return False
        # Joining is an idempotent ownership operation.  Goal coordination may
        # reassert the same queue command while a passenger waits for a shared
        # physical resource; replaying enter_facility_queue would duplicate
        # lifecycle evidence and reset semantic state without changing FIFO.
        if passenger in self.queue:
            return True
        if not self.is_available_for_queue:
            return False
        if self.queue.is_full:
            return False
        joined = self.queue.join(
            passenger,
            settle=settle_after_walking,
            preferred_slot_index=preferred_slot_index,
        )
        if not joined:
            return False
        passenger.enter_facility_queue(self.spec)
        return True

    def _queue_authorized(self, passenger: PassengerAgent, authority: str | None) -> bool:
        del passenger
        return authority == "goal_graph"

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
        self.queue.layout_positions(
            speed=speed,
            goal_label=f"{self.spec.label} queue slot",
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
            external_occupied_positions=self._queue_external_occupied_positions(),
            slot_index_offset=self._queue_layout_slot_index_offset(),
        )

    def _queue_external_occupied_positions(self) -> tuple[tuple[float, float], ...]:
        """Bodies outside the queue that occupy its physical layout domain."""

        return external_body_positions(
            self.model,
            level_id=self.spec.entry_level_id,
            excluded_passenger_ids=(
                int(passenger.unique_id) for passenger in self.queue
            ),
        )

    def _queue_layout_slot_index_offset(self) -> int:
        return 0

    def _queue_layout_speed_units_per_tick(self) -> float:
        scenario = self.model.scenario
        configured = float(scenario.walk_units_per_tick)
        tick_seconds = float(scenario.tick_seconds)
        physical = self._walking_speed_m_s() * tick_seconds
        simulation_clock = getattr(self.model, "simulation_clock", None)
        if simulation_clock is None or not bool(
            getattr(simulation_clock, "research_valid", False)
        ):
            return max(0.1, configured)
        return max(0.1, min(configured, physical))

    def _walking_speed_m_s(self) -> float:
        scenario = self.model.scenario
        tick_seconds = float(scenario.tick_seconds)
        configured_speed = float(scenario.walk_units_per_tick) / max(
            tick_seconds,
            1e-9,
        )
        return max(
            0.001,
            float(
                getattr(
                    scenario,
                    "jupedsim_desired_speed_mps",
                    configured_speed,
                )
            ),
        )

    def _serve_queue(self, train: TrainAgent | None = None) -> None:
        if not self.is_open:
            return
        if not self.queue:
            self.service_credit = 0.0
            return

        self.service_credit += self._service_groups_per_tick()
        release_count = min(len(self.queue), int(self.service_credit))
        release_index = 0
        self._service_release_positions_this_tick = []
        while self.queue and self.service_credit >= 1.0:
            passenger = self.queue[0]
            if self.queue.is_settling(passenger):
                break
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
        return self.effective_service_persons_per_min / group_size * scenario.tick_seconds / 60.0

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
        target = self._service_entry_position(release_index)
        distance = hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1])
        return distance <= self._service_ready_radius()

    def _service_ready_radius(self) -> float:
        scenario = self.model.scenario
        return max(
            float(scenario.jupedsim_target_radius_units),
            float(getattr(scenario, "personal_space_units", 0.8)) * 0.35,
        )

    def intercept_queue_approach_crossing(
        self,
        result: MovementResult,
        queue_target: tuple[float, float],
    ) -> MovementResult:
        guard = self.spec.queue_crossing_guard
        if result.reached or not guard.enabled:
            return result
        if not self._has_crossed_service_entry(
            result.position,
            queue_target,
            self._queue_crossing_service_entry_position(),
            tolerance=max(0.0, float(guard.tolerance_units)),
            lane_half_width=max(0.0, float(guard.lane_half_width_units)),
        ):
            return result
        return MovementResult(
            result.passenger_id,
            # Preserve the movement engine's authoritative coordinate.  The
            # guard changes only the semantic fact (the capture plane was
            # crossed); snapping Mesa to queue_target here leaves JuPedSim at
            # a different same-time position and creates a hidden authority
            # discontinuity on the next tick.
            self.model.clamp_position(result.position),
            reached=True,
        )

    def _queue_crossing_service_entry_position(self) -> tuple[float, float]:
        return self._service_entry_position(0)

    def _has_crossed_service_entry(
        self,
        position: tuple[float, float],
        queue_target: tuple[float, float],
        service_entry: tuple[float, float],
        *,
        tolerance: float,
        lane_half_width: float,
    ) -> bool:
        approach_vector = (
            service_entry[0] - queue_target[0],
            service_entry[1] - queue_target[1],
        )
        approach_length = hypot(approach_vector[0], approach_vector[1])
        if approach_length <= 0.001:
            return False

        unit = (
            approach_vector[0] / approach_length,
            approach_vector[1] / approach_length,
        )
        next_progress = self._projection_along(position, queue_target, unit)
        entry_progress = self._projection_along(service_entry, queue_target, unit)
        if next_progress < entry_progress - tolerance:
            return False

        lateral_distance = abs(
            self._projection_along(
                position,
                queue_target,
                (-unit[1], unit[0]),
            )
        )
        return lateral_distance <= lane_half_width

    def _projection_along(
        self,
        point: tuple[float, float],
        origin: tuple[float, float],
        unit: tuple[float, float],
    ) -> float:
        return (point[0] - origin[0]) * unit[0] + (point[1] - origin[1]) * unit[1]

    def _service_entry_position(self, release_index: int = 0) -> tuple[float, float]:
        return self._safe_queue_slot(max(0, int(release_index)))

    def _safe_queue_slot(self, index: int) -> tuple[float, float]:
        slot = self.model.clamp_position(self.spec.queue_layout.slot(max(0, int(index))))
        level_id = self.spec.entry_level_id
        try:
            area = self.model.jupedsim_walkable_area(level_id)
            return project_to_safe_point(
                area,
                slot,
                clearance=max(0.02, self.model.scenario.jupedsim_agent_radius_units * 1.05),
                require_inside=False,
            )
        except Exception:
            return slot

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

    def _release_position(
        self,
        passenger: PassengerAgent,
        release_index: int,
        *,
        base_position: tuple[float, float] | None = None,
    ) -> tuple[float, float]:
        base = self.spec.exit_position if base_position is None else base_position
        forward, lateral = self._release_axes()
        spacing = self._release_spacing()
        column_count = self._release_column_count()
        column_order = self._release_column_order(release_index)
        row = release_index // column_count
        candidates = self._release_candidates(base, forward, lateral, spacing, column_order, row)
        min_distance = self._release_min_distance()
        for candidate in candidates:
            projected = self._project_release_position(candidate)
            if not self._has_release_clearance(
                projected,
                min_distance,
                passenger=passenger,
            ):
                continue
            try:
                release_position = self.model.movement_backend.resolve_placement(
                    passenger,
                    projected,
                    level_id=self.spec.exit_level_id or self.spec.entry_level_id,
                )
            except Exception:
                continue
            if self._has_release_clearance(
                release_position,
                min_distance,
                passenger=passenger,
            ):
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
            graph = getattr(self.model.layout_graph, "station_graph", None)
            if graph is not None and self.spec.source_element_id is not None:
                exit_nodes = [
                    graph.nodes[node_id]
                    for node_id in graph.node_ids_for_element(self.spec.source_element_id)
                    if node_id in graph.nodes
                    and (
                        self.spec.exit_level_id is None
                        or graph.nodes[node_id].level_id == self.spec.exit_level_id
                    )
                ]
                if exit_nodes:
                    exit_node = min(
                        exit_nodes,
                        key=lambda node: hypot(
                            node.position[0] - ex,
                            node.position[1] - ey,
                        ),
                    )
                    for neighbor in graph.same_level_walk_neighbor_positions(
                        exit_node.node_id
                    ):
                        dx = neighbor[0] - ex
                        dy = neighbor[1] - ey
                        length = hypot(dx, dy)
                        if length > 0.001:
                            break
            if length <= 0.001:
                if self.spec.stage == "vertical_transfer":
                    raise RuntimeError(
                        f"vertical connector {self.facility_id!r} has no physical "
                        "release orientation in geometry or station topology"
                    )
                return (1.0, 0.0), (0.0, 1.0)
        forward = (dx / length, dy / length)
        lateral = (-forward[1], forward[0])
        return forward, lateral

    def _release_spacing(self) -> float:
        scenario = self.model.scenario
        clearance = self._release_min_distance() + float(self.spec.release_clearance_pad)
        personal = float(getattr(scenario, "personal_space_units", 0.8)) * float(
            self.spec.release_personal_factor
        )
        return max(
            float(self.spec.release_spacing_min),
            min(float(self.spec.release_spacing_max), max(clearance, personal)),
        )

    def _release_column_count(self) -> int:
        return max(1, int(self.spec.release_column_count))

    def _release_column_order(self, release_index: int) -> int:
        return self._centered_offsets(self._release_column_count())[
            int(release_index) % self._release_column_count()
        ]

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
        lateral_orders.extend(
            self._centered_offsets(max(0, int(self.spec.release_lateral_range)) * 2 + 1)
        )
        forward_steps = self._release_forward_steps(row)
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

    def _release_forward_steps(self, row: int) -> list[int]:
        extra = max(0, int(self.spec.release_forward_extra))
        steps = [row]
        if extra >= 1:
            steps.append(row + 1)
            steps.append(max(0, row - 1))
        steps.extend(row + offset for offset in range(2, extra + 1))
        return steps

    def _centered_offsets(self, count: int) -> tuple[int, ...]:
        orders = [0]
        offset = 1
        while len(orders) < max(1, count):
            orders.append(-offset)
            if len(orders) >= count:
                break
            orders.append(offset)
            offset += 1
        return tuple(orders)

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
        *,
        passenger: PassengerAgent | None = None,
    ) -> bool:
        for existing in self._service_release_positions_this_tick:
            if hypot(candidate[0] - existing[0], candidate[1] - existing[1]) < min_distance:
                return False
        release_level_id = self.spec.exit_level_id or self.spec.entry_level_id
        for other in self.model.passengers:
            if other is passenger:
                continue
            if release_level_id is not None and other.current_level_id != release_level_id:
                continue
            if hypot(candidate[0] - other.pos[0], candidate[1] - other.pos[1]) < min_distance:
                return False
        return True

    def _instant_pass_service(
        self,
        passenger: PassengerAgent,
        release_position: tuple[float, float],
    ) -> None:
        passenger.set_target(
            release_position,
            goal_kind="being_served",
            goal_label=self.spec.label,
            facility_id=self.spec.facility_id,
            stage=self.spec.stage,
        )
        passenger.pos = release_position
        passenger.suppress_movement_for_current_step()
        passenger.advance_after_movement(True)


def __getattr__(name: str):
    """Lazily preserve concrete-process imports from the historical module."""

    if name == "BoardingDoorProcessAgent":
        from .boarding_runtime import BoardingDoorProcessAgent

        value = BoardingDoorProcessAgent
    elif name in {"ActiveGatePass", "GateProcessAgent"}:
        from .gate_runtime import ActiveGatePass, GateProcessAgent

        value = {
            "ActiveGatePass": ActiveGatePass,
            "GateProcessAgent": GateProcessAgent,
        }[name]
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
