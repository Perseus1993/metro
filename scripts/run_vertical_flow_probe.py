from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from math import hypot
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any, Sequence

import mesa
from shapely.geometry import Polygon


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.facilities.process import (  # noqa: E402
    FacilityKind,
    FacilitySpec,
    QueueLayout,
)
from sandbox.metro_station_sandbox.facilities.runtime import (  # noqa: E402
    ElevatorProcessAgent,
    EscalatorProcessAgent,
    FacilityProcessAgent,
    StairsProcessAgent,
)
from sandbox.metro_station_sandbox.facilities.service_events import (  # noqa: E402
    FacilityServiceEvent,
)
from sandbox.metro_station_sandbox.facilities.vertical import (  # noqa: E402
    ElevatorConfig,
    EscalatorConfig,
    EscalatorMode,
    StairsConfig,
    VerticalFacilityConfig,
)
from sandbox.metro_station_sandbox.movement.backend import (  # noqa: E402
    BatchedJuPedSimMovementBackend,
    MovementBackend,
    MovementResult,
)
from metro_station.adapters.simulation.movement.facility_motion_trace import (  # noqa: E402
    FacilityMotionTraceRecorder,
)
from metro_station.adapters.simulation.compilation import (  # noqa: E402
    spatial_capacity as spatial_capacity_compiler,
)
from metro_station.adapters.simulation.compilation.geometry_reachability import (  # noqa: E402
    GeometryCompilePolicy,
)
from metro_station.adapters.simulation.runtime.goal_parity import (  # noqa: E402
    GoalParityRecorder,
)
from sandbox.metro_station_sandbox.movement.jps_adapter import JuPedSimAdapter  # noqa: E402
from sandbox.metro_station_sandbox.planning.plan import AgentState, FacilityStage  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "output" / "vertical_flow_probe"
DEFAULT_OUTPUT_STEM = "vertical_flow_probe"
DEFAULT_DEMANDS = (1800,)
DEFAULT_KINDS = (
    FacilityKind.ESCALATOR.value,
    FacilityKind.ELEVATOR.value,
    FacilityKind.STAIRS.value,
)
LEVEL_ID = "vertical_probe_entry"
VERTICAL_FACILITY_POSITION = (25.4, 6.0)
VERTICAL_EXIT_POSITION = (31.2, 6.0)

FIELDNAMES = (
    "run_id",
    "status",
    "clearance",
    "facility_kind",
    "demand_hour",
    "service_persons_per_min",
    "seed",
    "minutes",
    "tick_seconds",
    "drain_seconds",
    "group_size",
    "arrival_profile",
    "movement_backend",
    "jupedsim_operational_model",
    "jupedsim_status",
    "jupedsim_steps",
    "jupedsim_batches",
    "source_persons",
    "served_persons",
    "sink_persons",
    "unserved_persons",
    "completion_rate",
    "approach_persons_max",
    "queue_persons_max",
    "service_persons_max",
    "queue_persons_final",
    "mean_queue_wait_seconds",
    "p95_queue_wait_seconds",
    "mean_system_seconds",
    "p95_system_seconds",
    "departed_cabins",
    "last_departure_load_persons",
    "elapsed_seconds",
    "error_type",
    "error",
)


@dataclass(frozen=True)
class VerticalFlowScenario:
    tick_seconds: int
    group_size: int
    walk_units_per_tick: float
    movement_backend_name: str = "jupedsim"
    jupedsim_operational_model: str = "collision_free_speed"
    jupedsim_strict: bool = True
    jupedsim_iterations_per_tick: int = 20
    jupedsim_target_radius_units: float = 0.45
    jupedsim_desired_speed_mps: float = 1.2
    personal_space_units: float = 0.8
    jupedsim_agent_radius_units: float = 0.18
    jupedsim_clearance_multiplier: float = 2.2
    jupedsim_neighbor_radius_units: float = 2.4
    jupedsim_neighbor_sample_limit: int = 12


@dataclass(frozen=True)
class ProbeCase:
    facility_kind: str
    demand_hour: int
    service_persons_per_min: int
    seed: int

    @property
    def run_id(self) -> str:
        return (
            f"vertical_{self.facility_kind}_demand_{self.demand_hour}_"
            f"service_{self.service_persons_per_min}_seed_{self.seed}"
        )


@dataclass(frozen=True)
class OutputPaths:
    csv_path: Path
    json_path: Path
    markdown_path: Path
    animation_html_path: Path | None = None


@dataclass(frozen=True)
class ProbeRunResult:
    row: dict[str, Any]
    animation: dict[str, Any] | None


class LinearProbeMovementBackend(MovementBackend):
    """Minimal source-to-capture walking backend for vertical flow probes."""

    def move(self, passenger: "VerticalProbePassenger") -> MovementResult:
        x, y = passenger.pos
        tx, ty = passenger.target
        distance = hypot(tx - x, ty - y)
        step = float(passenger.model.scenario.walk_units_per_tick)
        radius = float(passenger.model.scenario.jupedsim_target_radius_units)
        if distance <= 0.001 or distance <= max(step, radius):
            return MovementResult(passenger.unique_id, passenger.target, reached=True)

        ratio = step / distance
        return MovementResult(
            passenger.unique_id,
            (x + (tx - x) * ratio, y + (ty - y) * ratio),
            reached=False,
        )

    def remove_passenger(self, passenger: "VerticalProbePassenger") -> None:
        return None


class VerticalProbePassenger:
    """Passenger contract needed by the shared vertical facility runtimes."""

    def __init__(
        self,
        model: "VerticalFlowProbeModel",
        *,
        unique_id: int,
        created_step: int,
        position: tuple[float, float],
    ) -> None:
        self.model = model
        self.unique_id = unique_id
        self.group_size = int(model.scenario.group_size)
        self.created_step = int(created_step)
        self.queue_join_step: int | None = None
        self.service_step: int | None = None
        self.departed_step: int | None = None
        self.intent = "vertical_source_to_sink"
        self.state = AgentState.WALKING_TO_VERTICAL.value
        self.pos = model.clamp_position(position)
        self.target = self.pos
        self.route: list[tuple[float, float]] = []
        self.current_level_id: str | None = LEVEL_ID
        self.assigned_facility_id: str | None = None
        self.passive_facility_service = False
        self.goal: dict[str, Any] = {
            "kind": "source",
            "label": "source",
            "target": self.pos,
            "facility_id": None,
            "stage": None,
        }

    @property
    def current_goal(self):
        return SimpleNamespace(
            target=self.target,
            facility_id=self.assigned_facility_id,
            stage=self.goal.get("stage"),
        )

    def set_target(
        self,
        target: tuple[float, float],
        *,
        goal_kind: str = "walk",
        goal_label: str = "target",
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        self.route = []
        self.target = self.model.clamp_position(target)
        self.goal = {
            "kind": goal_kind,
            "label": goal_label,
            "target": self.target,
            "facility_id": facility_id,
            "stage": stage.value if isinstance(stage, FacilityStage) else stage,
        }

    def set_route(
        self,
        points: Sequence[tuple[float, float]],
        *,
        goal_kind: str = "walk",
        goal_label: str = "route",
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        route = list(points)
        if not route:
            return
        self.target = self.model.clamp_position(route[0])
        self.route = [self.model.clamp_position(point) for point in route[1:]]
        self.goal = {
            "kind": goal_kind,
            "label": goal_label,
            "target": self.target,
            "facility_id": facility_id,
            "stage": stage.value if isinstance(stage, FacilityStage) else stage,
        }

    def set_passive_layout_target(
        self,
        target: tuple[float, float],
        *,
        goal_kind: str,
        goal_label: str,
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        """Mirror the production passive-layout ownership contract."""

        self.set_target(
            target,
            goal_kind=goal_kind,
            goal_label=goal_label,
            facility_id=facility_id,
            stage=stage,
        )

    def apply_movement_result(self, result: MovementResult) -> bool:
        self.pos = self.model.clamp_position(result.position)
        if not result.reached:
            return False
        return self._finish_current_target()

    def move_directly_toward_target(
        self,
        max_distance: float | None = None,
        *,
        occupied_positions: Sequence[tuple[float, float]] = (),
        min_clearance: float | None = None,
    ) -> bool:
        x, y = self.pos
        tx, ty = self.target
        distance = hypot(tx - x, ty - y)
        if distance <= 0.001:
            return self._finish_current_target()

        step = (
            float(max_distance)
            if max_distance is not None
            else float(self.model.scenario.walk_units_per_tick)
        )
        if step <= 0.0 or distance <= max(step, self.model.scenario.jupedsim_target_radius_units):
            candidate = self.target
        else:
            ratio = step / distance
            candidate = (x + (tx - x) * ratio, y + (ty - y) * ratio)

        cleared = self._clear_position(
            self.model.clamp_position(candidate),
            tuple(occupied_positions),
            min_clearance=min_clearance,
        )
        self.pos = cleared
        if hypot(cleared[0] - self.target[0], cleared[1] - self.target[1]) <= 0.001:
            return self._finish_current_target()
        return False

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        self.model.movement_backend.remove_passenger(self)
        self.passive_facility_service = False
        self.state = spec.queue_state
        self.assigned_facility_id = spec.facility_id
        self.current_level_id = spec.entry_level_id or self.current_level_id
        if self.queue_join_step is None:
            self.queue_join_step = self.model.step_index
        self.set_target(
            spec.queue_anchor,
            goal_kind="queued",
            goal_label=f"{spec.label} queue",
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def begin_facility_service(self, spec: FacilitySpec) -> None:
        self.model.movement_backend.remove_passenger(self)
        self.passive_facility_service = False
        self.state = spec.service_state
        self.assigned_facility_id = spec.facility_id
        self.current_level_id = spec.exit_level_id or self.current_level_id
        if self.service_step is None:
            self.service_step = self.model.step_index
        self.set_route(
            spec.release_route,
            goal_kind="being_served",
            goal_label=spec.label,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def advance_after_movement(self, reached: bool) -> None:
        if reached and self.state == AgentState.RIDING_VERTICAL.value:
            self.model.complete_departure(self)

    def remove(self) -> None:
        return None

    def _finish_current_target(self) -> bool:
        self.pos = self.target
        if not self.route:
            return True
        self.target = self.route.pop(0)
        self.goal["target"] = self.target
        return False

    def _clear_position(
        self,
        candidate: tuple[float, float],
        occupied_positions: tuple[tuple[float, float], ...],
        *,
        min_clearance: float | None,
    ) -> tuple[float, float]:
        clearance = (
            max(
                0.05,
                self.model.scenario.jupedsim_agent_radius_units
                * self.model.scenario.jupedsim_clearance_multiplier,
            )
            if min_clearance is None
            else max(0.0, float(min_clearance))
        )
        if _has_clearance(candidate, occupied_positions, clearance):
            return candidate

        x, y = self.pos
        for fraction in (0.75, 0.5, 0.25, 0.0):
            adjusted = self.model.clamp_position(
                (x + (candidate[0] - x) * fraction, y + (candidate[1] - y) * fraction)
            )
            if _has_clearance(adjusted, occupied_positions, clearance):
                return adjusted
        return self.pos


class VerticalFlowProbeModel(mesa.Model):
    """Source -> vertical facility queue/service -> sink micro-scene."""

    width = 36.0
    height = 12.0
    source_position = (2.0, 6.0)

    def __init__(
        self,
        *,
        scenario: VerticalFlowScenario,
        facility_kind: str,
        service_persons_per_min: int,
        seed: int,
    ) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"The use of the `seed` keyword argument is deprecated.*",
                category=FutureWarning,
            )
            super().__init__(seed=seed)
        self._scenario = scenario
        self.facility_kind = facility_kind
        self.step_index = 0
        self.passengers: list[VerticalProbePassenger] = []
        self.all_passengers: list[VerticalProbePassenger] = []
        self.sink_passengers: list[VerticalProbePassenger] = []
        self.frames: list[dict[str, Any]] = []
        self.facility_service_events: list[FacilityServiceEvent] = []
        self.facility_motion_trace_recorder = FacilityMotionTraceRecorder(
            sample_interval_seconds=0.2
        )
        self.goal_parity = GoalParityRecorder()
        self._facility_service_event_id = 0
        self._next_passenger_id = 1
        facility_spec = vertical_spec(
            kind=self.facility_kind,
            service_persons_per_min=service_persons_per_min,
        )
        self._facility_portal_binding = SimpleNamespace(
            facility_id=facility_spec.facility_id,
            entry_point=facility_spec.position,
            exit_point=facility_spec.exit_position,
            entry_level_id=facility_spec.entry_level_id,
            exit_level_id=facility_spec.exit_level_id,
            direction=facility_spec.direction,
            approach_slots=facility_spec.queue_layout.slots,
            approach_slot_indices=tuple(range(len(facility_spec.queue_layout.slots))),
            release_forward=(1.0, 0.0),
            release_lateral=(0.0, 1.0),
        )
        self.layout_graph = SimpleNamespace(
            geometry=SimpleNamespace(width=self.width, height=self.height),
            facility_portal_binding=self.facility_portal_binding,
        )
        self._spatial_capacity_slot_owners: dict[str, dict[int, int]] = {}
        self.jupedsim = JuPedSimAdapter()
        self.movement_backend = self._build_movement_backend()
        self._walkable_area = Polygon(
            [(0.0, 0.0), (self.width, 0.0), (self.width, self.height), (0.0, self.height)]
        )
        self._capacity_certificates: dict[str, object] = {}
        if facility_spec.kind == FacilityKind.ELEVATOR.value:
            self._install_elevator_capacity_certificates(facility_spec)
        self.layout_graph.spatial_capacity_certificate = (
            self.spatial_capacity_certificate
        )
        self.facility = self._build_facility(facility_spec)
        self.facilities_by_id = {self.facility.facility_id: self.facility}

    @property
    def scenario(self) -> VerticalFlowScenario:
        return self._scenario

    @scenario.setter
    def scenario(self, value: VerticalFlowScenario) -> None:
        self._scenario = value

    @property
    def current_time_seconds(self) -> float:
        return self.step_index * self.scenario.tick_seconds

    @property
    def sink_persons(self) -> int:
        return sum(passenger.group_size for passenger in self.sink_passengers)

    def next_facility_service_event_id(self) -> int:
        self._facility_service_event_id += 1
        return self._facility_service_event_id

    def facility_portal_binding(self, facility_id: str):
        """Expose the probe's compiled physical facade through the runtime API."""

        if facility_id != self._facility_portal_binding.facility_id:
            raise KeyError(facility_id)
        return self._facility_portal_binding

    def spatial_capacity_certificate(
        self,
        resource_kind: str,
        owner_id: str,
        **_filters,
    ):
        if owner_id != self._facility_portal_binding.facility_id:
            raise KeyError((resource_kind, owner_id))
        try:
            return self._capacity_certificates[resource_kind]
        except KeyError as exc:
            raise KeyError((resource_kind, owner_id)) from exc

    def _install_elevator_capacity_certificates(
        self,
        facility_spec: FacilitySpec,
    ) -> None:
        policy = GeometryCompilePolicy(
            agent_radius_m=float(self.scenario.jupedsim_agent_radius_units),
            target_radius_m=float(self.scenario.jupedsim_target_radius_units),
            personal_space_m=float(self.scenario.personal_space_units),
            clearance_multiplier=float(self.scenario.jupedsim_clearance_multiplier),
        )
        spacing = spatial_capacity_compiler._release_spacing(facility_spec, policy)
        required = int(facility_spec.vertical_config.elevator.batch_capacity)
        raw_domain = self._walkable_area
        safe_domain = raw_domain.buffer(-policy.agent_radius_m * 1.05)
        batch_plans, batch_paths = (
            spatial_capacity_compiler._compile_elevator_batch_plans(
                facility_spec,
                self._facility_portal_binding,
                raw_domain=raw_domain,
                safe_domain=safe_domain,
                blocked_positions=(),
                required_capacity=required,
                spacing=spacing,
                policy=policy,
            )
        )
        slots, paths = spatial_capacity_compiler._elevator_release_envelope(
            facility_spec,
            batch_paths,
            raw_domain=raw_domain,
            safe_domain=safe_domain,
            blocked_positions=(),
            spacing=spacing,
            policy=policy,
        )
        if len(batch_plans) != required or not slots or not paths:
            raise RuntimeError("vertical probe could not compile elevator capacity")
        common = {
            "owner_id": facility_spec.facility_id,
            "level_id": facility_spec.exit_level_id,
            "certified_body_capacity": required,
            "certified_person_capacity": required * self.scenario.group_size,
            "batch_plans": batch_plans,
            "batch_swept_paths": batch_paths,
        }
        self._capacity_certificates = {
            "release_apron": SimpleNamespace(
                certificate_id=f"probe:release:{facility_spec.facility_id}",
                resource_kind="release_apron",
                slots=tuple(slots),
                swept_paths=(),
                **common,
            ),
            "service_corridor": SimpleNamespace(
                certificate_id=f"probe:corridor:{facility_spec.facility_id}",
                resource_kind="service_corridor",
                slots=(),
                swept_paths=tuple(paths),
                **common,
            ),
        }

    def record_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)

    def clamp_position(self, position: tuple[float, float]) -> tuple[float, float]:
        return (
            max(0.0, min(self.width, float(position[0]))),
            max(0.0, min(self.height, float(position[1]))),
        )

    def jupedsim_walkable_area(self, level_id: str | None = None):
        return self._walkable_area

    def nearby_passengers(
        self,
        passenger: VerticalProbePassenger,
        radius: float,
    ) -> list[tuple[VerticalProbePassenger, float, float, float]]:
        nearby = []
        for other in self.passengers:
            if other is passenger:
                continue
            dx = other.pos[0] - passenger.pos[0]
            dy = other.pos[1] - passenger.pos[1]
            dist = hypot(dx, dy)
            if dist <= radius:
                nearby.append((other, dx, dy, dist))
        nearby.sort(key=lambda item: item[3])
        return nearby

    def spawn_source_passenger(self, *, local_index: int) -> VerticalProbePassenger:
        x, y = self.source_position
        side_offset = (local_index % 9 - 4) * 0.18
        row_offset = (local_index // 9) * 0.25
        passenger = VerticalProbePassenger(
            self,
            unique_id=self._next_passenger_id,
            created_step=self.step_index,
            position=(x - row_offset, y + side_offset),
        )
        self._next_passenger_id += 1
        self.passengers.append(passenger)
        self.all_passengers.append(passenger)
        return passenger

    def complete_departure(self, passenger: VerticalProbePassenger) -> None:
        if passenger.state == AgentState.DEPARTED.value:
            return
        self.movement_backend.remove_passenger(passenger)
        passenger.state = AgentState.DEPARTED.value
        passenger.departed_step = self.step_index
        self.sink_passengers.append(passenger)
        try:
            self.passengers.remove(passenger)
        except ValueError:
            return

    def run_step(self, *, arrivals: int) -> None:
        for local_index in range(max(0, int(arrivals))):
            self.spawn_source_passenger(local_index=local_index)

        self._target_approaching_passengers()
        for passenger, movement_result in self.movement_backend.step_all(list(self.passengers)):
            reached = passenger.apply_movement_result(movement_result)
            if reached and passenger.state == AgentState.WALKING_TO_VERTICAL.value:
                passenger_id = int(passenger.unique_id)
                preferred_slot = self.facility.queue.approach_slot_reservation(
                    passenger_id
                )
                joined = self.facility.join_queue(
                    passenger,
                    authority="goal_graph",
                    settle_after_walking=True,
                    preferred_slot_index=preferred_slot,
                )
                if joined:
                    self.facility.queue.release_approach_slot(passenger_id)

        self.facility.step()
        self.frames.append(self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        state_counts = Counter(passenger.state for passenger in self.passengers)
        state_counts[AgentState.DEPARTED.value] = len(self.sink_passengers)
        return {
            "step": self.step_index,
            "time_seconds": self.current_time_seconds,
            "passengers": [passenger_snapshot(passenger) for passenger in self.all_passengers],
            "approach_persons": state_counts[AgentState.WALKING_TO_VERTICAL.value],
            "queue_persons": self.facility.queue_persons,
            "service_persons": self._service_persons(),
            "served_persons": self.facility.served_persons,
            "sink_persons": self.sink_persons,
            "state_counts": dict(state_counts),
            "facility": self._facility_snapshot(),
            "movement": {
                "backend": type(self.movement_backend).__name__,
                "jupedsim_steps": int(getattr(self.movement_backend, "jps_step_count", 0) or 0),
                "jupedsim_batches": int(getattr(self.movement_backend, "jps_batch_count", 0) or 0),
            },
        }

    def _target_approaching_passengers(self) -> None:
        slots = self.facility.spec.queue_layout.slots
        for passenger in self.passengers:
            if passenger.state != AgentState.WALKING_TO_VERTICAL.value:
                continue
            passenger_id = int(passenger.unique_id)
            slot_index = self.facility.queue.approach_slot_reservation(passenger_id)
            if slot_index is None:
                slot_index = min(passenger_id - 1, len(slots) - 1)
                self.facility.queue.reserve_approach_slot(passenger_id, slot_index)
            passenger.set_target(
                slots[slot_index],
                goal_kind="walk",
                goal_label=f"{self.facility.spec.label} pre-capture",
                facility_id=self.facility.facility_id,
                stage=self.facility.spec.stage,
            )

    def _build_facility(self, spec: FacilitySpec) -> FacilityProcessAgent:
        if self.facility_kind == FacilityKind.ELEVATOR.value:
            return ElevatorProcessAgent(self, spec=spec)
        if self.facility_kind == FacilityKind.STAIRS.value:
            return StairsProcessAgent(self, spec=spec)
        return EscalatorProcessAgent(self, spec=spec)

    def _build_movement_backend(self) -> MovementBackend:
        requested = self.scenario.movement_backend_name
        if requested == "linear":
            return LinearProbeMovementBackend()
        if requested in {"jupedsim", "batched_jupedsim"}:
            if not self.jupedsim.status.available:
                raise RuntimeError(self.jupedsim.status.message)
            return BatchedJuPedSimMovementBackend(
                self.jupedsim,
                strict=self.scenario.jupedsim_strict,
            )
        raise ValueError(
            f"Unsupported movement backend {requested!r}. Use 'jupedsim' or 'linear'."
        )

    def _service_persons(self) -> int:
        if isinstance(self.facility, ElevatorProcessAgent):
            return int(self.facility.cabin_load_persons)
        return int(getattr(self.facility, "active_ride_persons", 0) or 0)

    def _facility_snapshot(self) -> dict[str, Any]:
        payload = {
            "kind": self.facility.spec.kind,
            "queue": int(self.facility.queue_persons),
            "served": int(self.facility.served_persons),
            "active": self._service_persons(),
        }
        if isinstance(self.facility, ElevatorProcessAgent):
            payload.update(
                {
                    "cabin_state": self.facility.cabin_state,
                    "departed_cabins": self.facility.departed_cabins,
                    "cabin_load": self.facility.cabin_load_persons,
                    "cycle_remaining_steps": self.facility.cycle_remaining_steps,
                }
            )
        return payload


def vertical_pre_capture_targets() -> tuple[tuple[float, float], ...]:
    # Each burst arrival needs a distinct body-clear tactical capture point.
    # Reusing five points for ten or more passengers creates exact colocation
    # before queue admission; physical compaction cannot untangle two bodies
    # that start at the same coordinate without a teleport.  The explicit
    # queue chain already supplies stable, correctly spaced approach places.
    return vertical_queue_slots()[1:]


def vertical_queue_slots() -> tuple[tuple[float, float], ...]:
    slots = [VERTICAL_FACILITY_POSITION]
    for row in range(16):
        x = VERTICAL_FACILITY_POSITION[0] - 0.75 - row * 0.62
        slots.append((x, 5.62))
        slots.append((x, 6.38))
    return tuple(slots)


def vertical_config(kind: str, service_persons_per_min: int) -> VerticalFacilityConfig:
    if kind == FacilityKind.ELEVATOR.value:
        return VerticalFacilityConfig(
            elevator=ElevatorConfig(
                batch_capacity=8,
                min_dispatch_persons=8,
                max_dispatch_wait_seconds=18.0,
                boarding_seconds=6.0,
                travel_seconds=24.0,
                unload_seconds=4.0,
                return_seconds=20.0,
            )
        )
    if kind == FacilityKind.STAIRS.value:
        return VerticalFacilityConfig(
            stairs=StairsConfig(
                base_capacity_ppm=max(1, int(service_persons_per_min)),
                fatigue_cost_up=0.6,
                fatigue_cost_down=0.18,
                bidirectional_conflict_factor=0.0,
            )
        )
    stand_capacity = max(1, int(service_persons_per_min))
    return VerticalFacilityConfig(
        escalator=EscalatorConfig(
            default_mode=EscalatorMode.STAND,
            ride_time_seconds=18.0,
            stand_capacity_ppm=stand_capacity,
            walk_capacity_ppm=max(1, round(stand_capacity * 1.35)),
            off_capacity_ppm=max(1, round(stand_capacity * 0.8)),
        )
    )


def vertical_spec(*, kind: str, service_persons_per_min: int) -> FacilitySpec:
    slots = vertical_queue_slots()
    label = {
        FacilityKind.ESCALATOR.value: "Escalator probe",
        FacilityKind.ELEVATOR.value: "Elevator probe",
        FacilityKind.STAIRS.value: "Stairs probe",
    }.get(kind, "Vertical probe")
    return FacilitySpec(
        facility_id=f"vertical:{kind}:probe:down:entry:exit",
        stage=FacilityStage.VERTICAL_TRANSFER.value,
        label=label,
        kind=kind,
        direction="down",
        position=VERTICAL_FACILITY_POSITION,
        queue_layout=QueueLayout(
            anchor=slots[0],
            per_row=2,
            col_step=(0.0, 0.76),
            row_step=(-0.62, 0.0),
            slots=slots,
        ),
        exit_position=VERTICAL_EXIT_POSITION,
        service_persons_per_min=int(service_persons_per_min),
        queue_state=AgentState.QUEUEING_VERTICAL.value,
        service_state=AgentState.RIDING_VERTICAL.value,
        release_route=(),
        speed_units_per_tick=0.72,
        travel_speed_m_s=0.72,
        traversal_width_m={"escalator": 1.0, "elevator": 2.2, "stairs": 3.0}[kind],
        entry_level_id=LEVEL_ID,
        exit_level_id="vertical_probe_exit",
        vertical_config=vertical_config(kind, service_persons_per_min),
    )


def passenger_snapshot(passenger: VerticalProbePassenger) -> dict[str, Any]:
    return {
        "id": int(passenger.unique_id),
        "x": round(float(passenger.pos[0]), 3),
        "y": round(float(passenger.pos[1]), 3),
        "state": str(passenger.state),
        "target": [
            round(float(passenger.target[0]), 3),
            round(float(passenger.target[1]), 3),
        ],
    }


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def parse_int_list(value: str) -> tuple[int, ...]:
    parsed: list[int] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        item = int(part)
        if item < 0:
            raise argparse.ArgumentTypeError("values must be >= 0")
        parsed.append(item)
    if not parsed:
        raise argparse.ArgumentTypeError("provide at least one integer")
    return tuple(parsed)


def parse_str_list(value: str) -> tuple[str, ...]:
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    if not parsed:
        raise argparse.ArgumentTypeError("provide at least one value")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run animated source -> vertical facility -> sink probes for "
            "escalators, elevators, and stairs."
        )
    )
    parser.add_argument("--kinds", type=parse_str_list, default=DEFAULT_KINDS)
    parser.add_argument("--demands", type=parse_int_list, default=DEFAULT_DEMANDS)
    parser.add_argument("--service-persons", type=parse_int_list, default=(18,))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seeds", type=parse_int_list, default=None)
    parser.add_argument("--minutes", type=positive_int, default=1)
    parser.add_argument("--tick-seconds", type=positive_int, default=1)
    parser.add_argument("--drain-seconds", type=nonnegative_int, default=420)
    parser.add_argument("--group-size", type=positive_int, default=1)
    parser.add_argument("--walk-units-per-tick", type=positive_float, default=0.7)
    parser.add_argument(
        "--movement-backend",
        choices=("jupedsim", "batched_jupedsim", "linear"),
        default="jupedsim",
    )
    parser.add_argument(
        "--jupedsim-model",
        choices=("collision_free_speed", "social_force"),
        default="collision_free_speed",
    )
    parser.add_argument("--jupedsim-iterations-per-tick", type=positive_int, default=20)
    parser.add_argument(
        "--arrival-profile",
        choices=("burst", "uniform"),
        default="burst",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    parser.add_argument("--html-out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser


def arrival_schedule(
    *,
    demand_hour: int,
    minutes: int,
    tick_seconds: int,
    group_size: int,
    profile: str,
) -> Counter[int]:
    horizon_steps = max(1, int(minutes * 60 / tick_seconds))
    total_persons = round(max(0, demand_hour) * minutes / 60.0)
    total_groups = round(total_persons / max(1, group_size))
    schedule: Counter[int] = Counter()
    if total_groups <= 0:
        return schedule

    if profile == "burst":
        schedule[0] = total_groups
        return schedule

    for index in range(total_groups):
        step = min(horizon_steps - 1, int(index * horizon_steps / total_groups))
        schedule[step] += 1
    return schedule


def build_cases(
    *,
    kinds: Sequence[str],
    demands: Sequence[int],
    service_persons: Sequence[int],
    seeds: Sequence[int],
) -> list[ProbeCase]:
    return [
        ProbeCase(
            facility_kind=kind,
            demand_hour=demand,
            service_persons_per_min=service,
            seed=seed,
        )
        for kind in kinds
        for demand in demands
        for service in service_persons
        for seed in seeds
    ]


def make_model(args: argparse.Namespace, case: ProbeCase) -> VerticalFlowProbeModel:
    scenario = VerticalFlowScenario(
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        walk_units_per_tick=args.walk_units_per_tick,
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        jupedsim_iterations_per_tick=args.jupedsim_iterations_per_tick,
    )
    return VerticalFlowProbeModel(
        scenario=scenario,
        facility_kind=case.facility_kind,
        service_persons_per_min=case.service_persons_per_min,
        seed=case.seed,
    )


def run_case(args: argparse.Namespace, case: ProbeCase) -> dict[str, Any]:
    return run_case_with_animation(args, case).row


def run_case_with_animation(args: argparse.Namespace, case: ProbeCase) -> ProbeRunResult:
    model = make_model(args, case)
    schedule = arrival_schedule(
        demand_hour=case.demand_hour,
        minutes=args.minutes,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        profile=args.arrival_profile,
    )
    arrival_horizon_steps = max(1, int(args.minutes * 60 / args.tick_seconds))
    drain_steps = max(0, round(int(args.drain_seconds) / args.tick_seconds))
    horizon_steps = arrival_horizon_steps + drain_steps
    started = time.perf_counter()

    for step in range(horizon_steps):
        model.step_index = step
        model.run_step(arrivals=schedule.get(step, 0))

    row = summarize_run(
        args=args,
        case=case,
        model=model,
        elapsed_seconds=time.perf_counter() - started,
    )
    return ProbeRunResult(
        row=row,
        animation=animation_payload_for_run(args=args, case=case, model=model, row=row),
    )


def summarize_run(
    *,
    args: argparse.Namespace,
    case: ProbeCase,
    model: VerticalFlowProbeModel,
    elapsed_seconds: float,
) -> dict[str, Any]:
    source_persons = sum(passenger.group_size for passenger in model.all_passengers)
    sink_persons = int(model.sink_persons)
    unserved_persons = max(0, source_persons - sink_persons)
    queue_wait_seconds = [
        (passenger.service_step - passenger.queue_join_step) * args.tick_seconds
        for passenger in model.all_passengers
        if passenger.queue_join_step is not None and passenger.service_step is not None
    ]
    system_seconds = [
        (passenger.departed_step - passenger.created_step) * args.tick_seconds
        for passenger in model.all_passengers
        if passenger.departed_step is not None
    ]
    facility = model.facility
    return {
        "run_id": case.run_id,
        "status": "ok",
        "clearance": "cleared" if unserved_persons == 0 else "backlog",
        "facility_kind": case.facility_kind,
        "demand_hour": case.demand_hour,
        "service_persons_per_min": case.service_persons_per_min,
        "seed": case.seed,
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "drain_seconds": args.drain_seconds,
        "group_size": args.group_size,
        "arrival_profile": args.arrival_profile,
        "movement_backend": type(model.movement_backend).__name__,
        "jupedsim_operational_model": model.scenario.jupedsim_operational_model,
        "jupedsim_status": model.jupedsim.status.message,
        "jupedsim_steps": int(getattr(model.movement_backend, "jps_step_count", 0) or 0),
        "jupedsim_batches": int(getattr(model.movement_backend, "jps_batch_count", 0) or 0),
        "source_persons": source_persons,
        "served_persons": int(facility.served_persons),
        "sink_persons": sink_persons,
        "unserved_persons": unserved_persons,
        "completion_rate": round(sink_persons / source_persons, 4) if source_persons else None,
        "approach_persons_max": max_frame_value(model.frames, "approach_persons"),
        "queue_persons_max": max_frame_value(model.frames, "queue_persons"),
        "service_persons_max": max_frame_value(model.frames, "service_persons"),
        "queue_persons_final": int(facility.queue_persons),
        "mean_queue_wait_seconds": round(mean(queue_wait_seconds), 2)
        if queue_wait_seconds
        else 0.0,
        "p95_queue_wait_seconds": round(percentile(queue_wait_seconds, 0.95), 2),
        "mean_system_seconds": round(mean(system_seconds), 2) if system_seconds else 0.0,
        "p95_system_seconds": round(percentile(system_seconds, 0.95), 2),
        "departed_cabins": getattr(facility, "departed_cabins", None),
        "last_departure_load_persons": getattr(facility, "last_departure_load_persons", None),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "error_type": None,
        "error": None,
    }


def max_frame_value(frames: Sequence[dict[str, Any]], key: str) -> int:
    return max((int(frame.get(key, 0) or 0) for frame in frames), default=0)


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def error_row(args: argparse.Namespace, case: ProbeCase, exc: Exception) -> dict[str, Any]:
    row = {field: None for field in FIELDNAMES}
    row.update(
        {
            "run_id": case.run_id,
            "status": "error",
            "facility_kind": case.facility_kind,
            "demand_hour": case.demand_hour,
            "service_persons_per_min": case.service_persons_per_min,
            "seed": case.seed,
            "minutes": args.minutes,
            "tick_seconds": args.tick_seconds,
            "drain_seconds": args.drain_seconds,
            "group_size": args.group_size,
            "arrival_profile": args.arrival_profile,
            "movement_backend": args.movement_backend,
            "jupedsim_operational_model": args.jupedsim_model,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    )
    return row


def animation_payload_for_run(
    *,
    args: argparse.Namespace,
    case: ProbeCase,
    model: VerticalFlowProbeModel,
    row: dict[str, Any],
) -> dict[str, Any]:
    facility = model.facility
    return {
        "run_id": case.run_id,
        "label": (
            f"{case.facility_kind}, demand {case.demand_hour}/h, "
            f"service {case.service_persons_per_min}/min"
        ),
        "scenario": {
            "minutes": args.minutes,
            "tick_seconds": args.tick_seconds,
            "drain_seconds": args.drain_seconds,
            "arrival_profile": args.arrival_profile,
            "movement_backend": row.get("movement_backend"),
            "jupedsim_operational_model": row.get("jupedsim_operational_model"),
            "jupedsim_status": row.get("jupedsim_status"),
            "world_width": model.width,
            "world_height": model.height,
            "facility_kind": case.facility_kind,
            "source_position": list(model.source_position),
            "facility_position": list(facility.spec.position),
            "pre_capture_targets": [list(point) for point in vertical_pre_capture_targets()],
            "queue_anchor": list(facility.spec.queue_anchor),
            "queue_slots": [list(point) for point in vertical_queue_slots()],
            "exit_position": list(facility.spec.exit_position),
        },
        "summary": {
            key: row.get(key)
            for key in (
                "clearance",
                "source_persons",
                "sink_persons",
                "unserved_persons",
                "completion_rate",
                "approach_persons_max",
                "queue_persons_max",
                "service_persons_max",
                "p95_system_seconds",
                "departed_cabins",
                "last_departure_load_persons",
                "movement_backend",
                "jupedsim_steps",
                "jupedsim_batches",
            )
        },
        "frames": model.frames,
    }


def run_case_results(
    args: argparse.Namespace,
    cases: Sequence[ProbeCase],
) -> list[ProbeRunResult]:
    results: list[ProbeRunResult] = []
    for index, case in enumerate(cases, start=1):
        if not args.quiet:
            print(f"[VERTICAL-FLOW] {index}/{len(cases)} {case.run_id}")
        try:
            results.append(run_case_with_animation(args, case))
        except Exception as exc:  # noqa: BLE001
            results.append(ProbeRunResult(row=error_row(args, case, exc), animation=None))
    return results


def resolve_output_paths(args: argparse.Namespace) -> OutputPaths:
    out_dir = args.out_dir
    stem = args.output_stem
    return OutputPaths(
        csv_path=args.csv_out or out_dir / f"{stem}.csv",
        json_path=args.json_out or out_dir / f"{stem}.json",
        markdown_path=args.md_out or out_dir / f"{stem}.md",
        animation_html_path=args.html_out or out_dir / f"{stem}_animation.html",
    )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    return value


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in FIELDNAMES})


def aggregate_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    backlog_rows = [row for row in ok_rows if row.get("clearance") != "cleared"]
    return {
        "runs": len(rows),
        "ok": len(ok_rows),
        "errors": len(rows) - len(ok_rows),
        "backlog": len(backlog_rows),
        "worst_unserved_persons": max(
            (int(row.get("unserved_persons") or 0) for row in ok_rows),
            default=0,
        ),
        "worst_queue_persons_max": max(
            (int(row.get("queue_persons_max") or 0) for row in ok_rows),
            default=0,
        ),
        "worst_service_persons_max": max(
            (int(row.get("service_persons_max") or 0) for row in ok_rows),
            default=0,
        ),
    }


def metadata_for(args: argparse.Namespace, cases: Sequence[ProbeCase]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "scripts.run_vertical_flow_probe",
        "case_count": len(cases),
        "minutes": args.minutes,
        "tick_seconds": args.tick_seconds,
        "drain_seconds": args.drain_seconds,
        "group_size": args.group_size,
        "arrival_profile": args.arrival_profile,
        "movement_backend": args.movement_backend,
        "jupedsim_operational_model": args.jupedsim_model,
        "jupedsim_iterations_per_tick": args.jupedsim_iterations_per_tick,
        "kinds": list(args.kinds),
        "demands": list(args.demands),
        "service_persons": list(args.service_persons),
    }


def write_json_summary(
    path: Path,
    *,
    args: argparse.Namespace,
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata_for(args, cases),
        "summary": aggregate_summary(rows),
        "runs": list(rows),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: Sequence[dict[str, Any]]) -> str:
    columns = (
        ("status", "status"),
        ("clearance", "clearance"),
        ("kind", "facility_kind"),
        ("demand/h", "demand_hour"),
        ("service/min", "service_persons_per_min"),
        ("source", "source_persons"),
        ("sink", "sink_persons"),
        ("unserved", "unserved_persons"),
        ("max_q", "queue_persons_max"),
        ("max_service", "service_persons_max"),
        ("p95_q_s", "p95_queue_wait_seconds"),
        ("p95_sys_s", "p95_system_seconds"),
        ("cabins", "departed_cabins"),
    )
    header = "| " + " | ".join(label for label, _key in columns) + " |"
    divider = "| " + " | ".join("---" for _label, _key in columns) + " |"
    body = [
        "| " + " | ".join(markdown_cell(row.get(key)) for _label, key in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def write_markdown_summary(
    path: Path,
    *,
    args: argparse.Namespace,
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata_for(args, cases)
    summary = aggregate_summary(rows)
    content = "\n".join(
        [
            "# Vertical Flow Probe Summary",
            "",
            f"- generated_at: {meta['generated_at']}",
            f"- cases: {summary['runs']}",
            f"- ok: {summary['ok']}",
            f"- errors: {summary['errors']}",
            f"- backlog: {summary['backlog']}",
            f"- worst_unserved_persons: {summary['worst_unserved_persons']}",
            f"- worst_queue_persons_max: {summary['worst_queue_persons_max']}",
            f"- worst_service_persons_max: {summary['worst_service_persons_max']}",
            f"- arrival_profile: {args.arrival_profile}",
            f"- movement_backend: {args.movement_backend}",
            "- process_scope: source -> JuPedSim vertical approach -> queue/service -> sink",
            "- excluded_scope: gates, platforms, trains, full-station renderer",
            "",
            markdown_table(rows),
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def write_outputs(
    paths: OutputPaths,
    *,
    args: argparse.Namespace,
    cases: Sequence[ProbeCase],
    rows: Sequence[dict[str, Any]],
    animations: Sequence[dict[str, Any]] | None = None,
) -> None:
    write_csv(paths.csv_path, rows)
    write_json_summary(paths.json_path, args=args, cases=cases, rows=rows)
    write_markdown_summary(paths.markdown_path, args=args, cases=cases, rows=rows)
    if animations and paths.animation_html_path is not None:
        write_animation_html(paths.animation_html_path, animations=animations)


def write_animation_html(path: Path, *, animations: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "title": "Vertical Flow Probe",
        "runs": list(animations),
    }
    encoded_payload = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(animation_html_document(encoded_payload), encoding="utf-8")


def animation_html_document(encoded_payload: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape("Vertical Flow Probe")}</title>
<style>
:root {{
  color-scheme: light;
  font-family: Arial, Helvetica, sans-serif;
  background: #f4f5f7;
  color: #1d252c;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr;
}}
header {{
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  background: #ffffff;
  border-bottom: 1px solid #d7dde4;
}}
h1 {{
  margin: 0;
  font-size: 18px;
  font-weight: 700;
}}
.toolbar {{
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}}
button, select {{
  height: 34px;
  border: 1px solid #bdc7d0;
  background: #ffffff;
  color: #1d252c;
  border-radius: 6px;
  padding: 0 10px;
  font: inherit;
}}
button {{
  min-width: 36px;
  cursor: pointer;
}}
select {{
  max-width: min(58vw, 430px);
}}
main {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) 270px;
  min-height: 0;
}}
.stage {{
  min-width: 0;
  min-height: 0;
  padding: 14px;
}}
canvas {{
  display: block;
  width: 100%;
  height: calc(100vh - 92px);
  min-height: 430px;
  background: #eef2f4;
  border: 1px solid #ccd5dd;
  border-radius: 8px;
}}
.panel {{
  border-left: 1px solid #d7dde4;
  background: #ffffff;
  padding: 14px;
  display: grid;
  gap: 12px;
  align-content: start;
}}
.stat {{
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #edf0f3;
  font-size: 13px;
}}
.stat strong {{
  font-size: 18px;
}}
.timeline {{
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 10px;
}}
input[type="range"] {{
  width: 100%;
}}
.legend {{
  display: grid;
  gap: 8px;
  font-size: 12px;
}}
.legend-row {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.dot {{
  width: 11px;
  height: 11px;
  border-radius: 50%;
}}
@media (max-width: 820px) {{
  header, main {{
    grid-template-columns: 1fr;
  }}
  .toolbar {{
    justify-content: flex-start;
  }}
  .panel {{
    border-left: 0;
    border-top: 1px solid #d7dde4;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  canvas {{
    height: 58vh;
    min-height: 330px;
  }}
}}
</style>
</head>
<body>
<header>
  <h1>Vertical Flow Probe</h1>
  <div class="toolbar">
    <select id="runSelect" aria-label="Run"></select>
    <button id="playButton" title="Play/Pause" aria-label="Play/Pause">⏸</button>
    <button id="resetButton" title="Reset" aria-label="Reset">↺</button>
    <select id="speedSelect" aria-label="Speed">
      <option value="1" selected>1x</option>
      <option value="2">2x</option>
      <option value="4">4x</option>
      <option value="8">8x</option>
    </select>
  </div>
  <div class="timeline">
    <input id="timeline" type="range" min="0" value="0" step="0.01">
    <span id="clock">0s</span>
  </div>
</header>
<main>
  <section class="stage">
    <canvas id="canvas"></canvas>
  </section>
  <aside class="panel">
    <div class="stat"><span>kind</span><strong id="kindValue">-</strong></div>
    <div class="stat"><span>backend</span><strong id="backendValue">-</strong></div>
    <div class="stat"><span>jps steps</span><strong id="jpsValue">0</strong></div>
    <div class="stat"><span>source</span><strong id="sourceValue">0</strong></div>
    <div class="stat"><span>approach</span><strong id="approachValue">0</strong></div>
    <div class="stat"><span>queue</span><strong id="queueValue">0</strong></div>
    <div class="stat"><span>service</span><strong id="serviceValue">0</strong></div>
    <div class="stat"><span>sink</span><strong id="sinkValue">0</strong></div>
    <div class="stat"><span>unserved</span><strong id="unservedValue">0</strong></div>
    <div class="stat"><span>cabins</span><strong id="cabinsValue">-</strong></div>
    <div class="stat"><span>clearance</span><strong id="clearanceValue">-</strong></div>
    <div class="legend">
      <div class="legend-row"><span class="dot" style="background:#2f6f9f"></span> walking</div>
      <div class="legend-row"><span class="dot" style="background:#bf8f00"></span> queue</div>
      <div class="legend-row"><span class="dot" style="background:#7b61b4"></span> riding</div>
      <div class="legend-row"><span class="dot" style="background:#2f8f5b"></span> sink</div>
    </div>
  </aside>
</main>
<script>
const VERTICAL_FLOW_ANIMATION_DATA = {encoded_payload};
window.VERTICAL_FLOW_ANIMATION_DATA = VERTICAL_FLOW_ANIMATION_DATA;
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const runSelect = document.getElementById("runSelect");
const playButton = document.getElementById("playButton");
const resetButton = document.getElementById("resetButton");
const speedSelect = document.getElementById("speedSelect");
const timeline = document.getElementById("timeline");
const clock = document.getElementById("clock");
let runIndex = 0;
let frameValue = 0;
let playing = true;
let lastTime = performance.now();

for (const [index, run] of VERTICAL_FLOW_ANIMATION_DATA.runs.entries()) {{
  const option = document.createElement("option");
  option.value = String(index);
  option.textContent = run.label;
  runSelect.append(option);
}}

function currentRun() {{
  return VERTICAL_FLOW_ANIMATION_DATA.runs[runIndex];
}}

function currentFrames() {{
  return currentRun().frames || [];
}}

function resizeCanvas() {{
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}}

function worldToScreen(point) {{
  const run = currentRun();
  const width = run.scenario.world_width;
  const height = run.scenario.world_height;
  const rect = canvas.getBoundingClientRect();
  const pad = Math.max(24, Math.min(rect.width, rect.height) * 0.08);
  const sx = (rect.width - pad * 2) / width;
  const sy = (rect.height - pad * 2) / height;
  const scale = Math.min(sx, sy);
  const ox = (rect.width - width * scale) / 2;
  const oy = (rect.height - height * scale) / 2;
  return [ox + point[0] * scale, oy + point[1] * scale, scale];
}}

function frameAt(value) {{
  const frames = currentFrames();
  if (!frames.length) return null;
  const leftIndex = Math.max(0, Math.min(frames.length - 1, Math.floor(value)));
  const rightIndex = Math.max(0, Math.min(frames.length - 1, leftIndex + 1));
  const t = Math.max(0, Math.min(1, value - leftIndex));
  return {{ left: frames[leftIndex], right: frames[rightIndex], t }};
}}

function passengersAt(framePair) {{
  if (!framePair) return [];
  const leftById = new Map((framePair.left.passengers || []).map((p) => [p.id, p]));
  const passengers = [];
  for (const right of framePair.right.passengers || []) {{
    const left = leftById.get(right.id) || right;
    const t = framePair.t;
    passengers.push({{
      id: right.id,
      x: left.x + (right.x - left.x) * t,
      y: left.y + (right.y - left.y) * t,
      state: right.state,
    }});
  }}
  return passengers;
}}

function draw() {{
  resizeCanvas();
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  drawScene();
  const pair = frameAt(frameValue);
  if (pair) {{
    drawPassengers(passengersAt(pair));
    updateStats(pair.left);
    clock.textContent = `${{Math.round(pair.left.time_seconds || 0)}}s`;
  }}
}}

function drawScene() {{
  const run = currentRun();
  const source = worldToScreen(run.scenario.source_position);
  const exit = worldToScreen(run.scenario.exit_position);
  const facility = worldToScreen(run.scenario.facility_position);
  const rect = canvas.getBoundingClientRect();
  ctx.fillStyle = "#e7edf1";
  ctx.fillRect(0, 0, rect.width, rect.height);
  drawZone(source, 52, "#d8ecf4", "#2f6f9f", "SOURCE");
  drawZone(exit, 58, "#dff0e7", "#2f8f5b", "SINK");
  drawPreCapture(run.scenario.pre_capture_targets || []);
  drawQueue(run.scenario.queue_slots || []);
  drawFacility(run.scenario.facility_kind, run.scenario.facility_position, run.scenario.exit_position);
  ctx.strokeStyle = "#9aa7b1";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(source[0] + 42, source[1]);
  const targets = run.scenario.pre_capture_targets || [];
  if (targets.length) {{
    const merge = worldToScreen(targets[Math.floor(targets.length / 2)]);
    ctx.lineTo(merge[0], merge[1]);
  }}
  ctx.lineTo(facility[0] - 24, facility[1]);
  ctx.moveTo(facility[0] + 24, facility[1]);
  ctx.lineTo(exit[0] - 42, exit[1]);
  ctx.stroke();
}}

function drawZone(point, radius, fill, stroke, label) {{
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(point[0], point[1], radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = stroke;
  ctx.font = "12px Arial";
  ctx.textAlign = "center";
  ctx.fillText(label, point[0], point[1] + radius + 18);
}}

function drawPreCapture(targets) {{
  ctx.fillStyle = "rgba(47, 111, 159, 0.08)";
  ctx.strokeStyle = "rgba(47, 111, 159, 0.32)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (const target of targets) {{
    const p = worldToScreen(target);
    ctx.moveTo(p[0] + 15, p[1]);
    ctx.arc(p[0], p[1], 15, 0, Math.PI * 2);
  }}
  ctx.fill();
  ctx.stroke();
}}

function drawQueue(slots) {{
  ctx.strokeStyle = "#bf8f00";
  ctx.lineWidth = 1.4;
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  for (const slot of slots.slice(0, 28)) {{
    const p = worldToScreen(slot);
    ctx.moveTo(p[0], p[1] - 13);
    ctx.lineTo(p[0], p[1] + 13);
  }}
  ctx.stroke();
  ctx.setLineDash([]);
}}

function drawFacility(kind, startPoint, exitPoint) {{
  const start = worldToScreen(startPoint);
  const end = worldToScreen(exitPoint);
  ctx.strokeStyle = kind === "elevator" ? "#455a64" : "#263238";
  ctx.fillStyle = "rgba(123, 97, 180, 0.12)";
  ctx.lineWidth = 6;
  if (kind === "elevator") {{
    ctx.fillRect(start[0] - 22, start[1] - 42, 44, 84);
    ctx.strokeRect(start[0] - 22, start[1] - 42, 44, 84);
    ctx.fillRect(end[0] - 22, end[1] - 42, 44, 84);
    ctx.strokeRect(end[0] - 22, end[1] - 42, 44, 84);
    ctx.beginPath();
    ctx.moveTo(start[0] + 22, start[1]);
    ctx.lineTo(end[0] - 22, end[1]);
    ctx.stroke();
  }} else {{
    ctx.beginPath();
    ctx.moveTo(start[0], start[1] - 24);
    ctx.lineTo(end[0], end[1] - 24);
    ctx.lineTo(end[0], end[1] + 24);
    ctx.lineTo(start[0], start[1] + 24);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    if (kind === "stairs") {{
      ctx.lineWidth = 1.2;
      for (let i = 0; i < 9; i += 1) {{
        const x = start[0] + (end[0] - start[0]) * (i / 8);
        ctx.beginPath();
        ctx.moveTo(x, start[1] - 24);
        ctx.lineTo(x, start[1] + 24);
        ctx.stroke();
      }}
    }}
  }}
  ctx.fillStyle = "#263238";
  ctx.font = "12px Arial";
  ctx.textAlign = "center";
  ctx.fillText(kind.toUpperCase(), start[0], start[1] - 54);
}}

function drawPassengers(passengers) {{
  for (const p of displayPassengers(passengers)) {{
    const screen = worldToScreen([p.displayX ?? p.x, p.displayY ?? p.y]);
    const color = colorForState(p.state);
    ctx.fillStyle = color;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(screen[0], screen[1], 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = "9px Arial";
    ctx.textAlign = "center";
    ctx.fillText(String(p.id), screen[0], screen[1] + 3);
  }}
}}

function displayPassengers(passengers) {{
  const run = currentRun();
  if ((run.scenario.facility_kind || "") !== "elevator") return passengers;

  const visible = passengers.map((p) => ({{ ...p }}));
  const ridingByPosition = new Map();
  for (const p of visible) {{
    if (p.state !== "riding_vertical") continue;
    const key = `${{Math.round(p.x * 20) / 20}},${{Math.round(p.y * 20) / 20}}`;
    if (!ridingByPosition.has(key)) ridingByPosition.set(key, []);
    ridingByPosition.get(key).push(p);
  }}

  for (const group of ridingByPosition.values()) {{
    if (group.length <= 1) continue;
    group.sort((a, b) => a.id - b.id);
    const rows = Math.ceil(group.length / 2);
    for (const [index, p] of group.entries()) {{
      const col = index % 2;
      const row = Math.floor(index / 2);
      const dx = col === 0 ? -0.55 : 0.55;
      const dy = (row - (rows - 1) / 2) * 0.58;
      p.displayX = p.x + dx;
      p.displayY = p.y + dy;
    }}
  }}
  return visible;
}}

function colorForState(state) {{
  if (state === "departed") return "#2f8f5b";
  if (state === "queueing_vertical") return "#bf8f00";
  if (state === "riding_vertical") return "#7b61b4";
  return "#2f6f9f";
}}

function updateStats(frame) {{
  const run = currentRun();
  document.getElementById("kindValue").textContent = run.scenario.facility_kind || "-";
  document.getElementById("sourceValue").textContent = run.summary.source_persons ?? 0;
  document.getElementById("backendValue").textContent = (
    run.summary.movement_backend || run.scenario.movement_backend || "-"
  ).replace("MovementBackend", "");
  document.getElementById("jpsValue").textContent = run.summary.jupedsim_steps ?? 0;
  document.getElementById("approachValue").textContent = frame.approach_persons ?? 0;
  document.getElementById("queueValue").textContent = frame.queue_persons ?? 0;
  document.getElementById("serviceValue").textContent = frame.service_persons ?? 0;
  document.getElementById("sinkValue").textContent = frame.sink_persons ?? 0;
  document.getElementById("unservedValue").textContent = run.summary.unserved_persons ?? 0;
  document.getElementById("cabinsValue").textContent = run.summary.departed_cabins ?? "-";
  document.getElementById("clearanceValue").textContent = run.summary.clearance ?? "-";
}}

function resetTimeline() {{
  frameValue = 0;
  timeline.max = String(Math.max(0, currentFrames().length - 1));
  timeline.value = "0";
  draw();
}}

function step(now) {{
  const elapsed = (now - lastTime) / 1000;
  lastTime = now;
  if (playing && currentFrames().length > 1) {{
    const speed = Number(speedSelect.value || 1);
    frameValue += elapsed * speed;
    if (frameValue >= currentFrames().length - 1) {{
      frameValue = currentFrames().length - 1;
      playing = false;
      playButton.textContent = "▶";
    }}
    timeline.value = String(frameValue);
    draw();
  }}
  requestAnimationFrame(step);
}}

runSelect.addEventListener("change", () => {{
  runIndex = Number(runSelect.value || 0);
  playing = true;
  playButton.textContent = "⏸";
  resetTimeline();
}});
playButton.addEventListener("click", () => {{
  playing = !playing;
  playButton.textContent = playing ? "⏸" : "▶";
}});
resetButton.addEventListener("click", () => {{
  playing = true;
  playButton.textContent = "⏸";
  resetTimeline();
}});
timeline.addEventListener("input", () => {{
  frameValue = Number(timeline.value || 0);
  draw();
}});
window.addEventListener("resize", draw);
resetTimeline();
requestAnimationFrame(step);
</script>
</body>
</html>
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeds = args.seeds or (args.seed,)
    cases = build_cases(
        kinds=args.kinds,
        demands=args.demands,
        service_persons=args.service_persons,
        seeds=seeds,
    )
    results = run_case_results(args, cases)
    rows = [result.row for result in results]
    animations = [result.animation for result in results if result.animation is not None]
    paths = resolve_output_paths(args)
    write_outputs(paths, args=args, cases=cases, rows=rows, animations=animations)

    summary = aggregate_summary(rows)
    print(f"[VERTICAL-FLOW] wrote_csv={paths.csv_path.resolve()}")
    print(f"[VERTICAL-FLOW] wrote_json={paths.json_path.resolve()}")
    print(f"[VERTICAL-FLOW] wrote_markdown={paths.markdown_path.resolve()}")
    if paths.animation_html_path is not None:
        print(f"[VERTICAL-FLOW] wrote_animation={paths.animation_html_path.resolve()}")
    print(
        "[VERTICAL-FLOW] "
        f"runs={summary['runs']} ok={summary['ok']} errors={summary['errors']} "
        f"backlog={summary['backlog']} worst_unserved={summary['worst_unserved_persons']}"
    )
    return 1 if summary["errors"] else 0


def _has_clearance(
    candidate: tuple[float, float],
    occupied_positions: tuple[tuple[float, float], ...],
    clearance: float,
) -> bool:
    return all(
        hypot(candidate[0] - other[0], candidate[1] - other[1]) >= clearance
        for other in occupied_positions
    )


if __name__ == "__main__":
    raise SystemExit(main())
