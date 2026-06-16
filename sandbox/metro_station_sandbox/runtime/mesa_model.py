from __future__ import annotations

from collections import Counter, defaultdict
from math import cos as math_cos
from math import hypot
from math import sin as math_sin
from collections.abc import Callable
from typing import Any

import mesa
from shapely.geometry import Point as ShapelyPoint

from ..agents.passenger import PassengerAgent
from ..agents.staff import AdminAgent
from ..agents.transit import PlatformAgent, TrainAgent
from ..planning.plan import (
    CROWD_INTERACTION_STATES,
    AgentIntent,
    AgentPlan,
    AgentState,
    FacilityStage,
    RouteKey,
)
from .audit import AuditLogger
from .demand_scheduler import DemandScheduler
from ..station.compiler import DesignCompiler
from ..facilities.choice import DefaultFacilityChoicePolicy, FacilityChoicePolicy, StaffGuidedPolicy
from ..facilities.filters import filter_boarding_doors_for_platform, filter_platforms_for_passenger
from ..facilities.runtime import FacilityProcessAgent, facility_agent_for_spec
from ..facilities.service_events import FacilityServiceEvent
from ..station.geometry import level_walkable_geometry, project_to_safe_point
from ..movement.jps_adapter import JuPedSimAdapter
from .metrics import (
    average_system_minutes,
    average_walk_speed_factor,
    crowding_index,
    gate_queue_persons,
    platform_waiting_persons,
    station_persons,
    vertical_queue_persons,
)
from ..movement.backend import (
    BatchedJuPedSimMovementBackend,
    JuPedSimMovementBackend,
    MovementBackend,
)
from ..planning.factory import plan_for_station_graph
from ..planning.progress import ProgressMonitor
from ..station.scenario import StationSandboxScenario
from ..planning.selection import pick_least_loaded
from .snapshots import SnapshotBuilder


class MetroStationModel(mesa.Model):
    """Mesa model for a single-station passenger flow sandbox."""

    def __init__(
        self,
        scenario: StationSandboxScenario,
        *,
        seed: int = 42,
        facility_choice_policy: FacilityChoicePolicy | None = None,
        movement_backend: MovementBackend | None = None,
    ) -> None:
        super().__init__(seed=seed)
        # Mesa 3.5's scenario setter mutates the scenario object; keep this frozen dataclass immutable.
        self._scenario = scenario
        self.step_index = 0
        self.passengers: list[PassengerAgent] = []
        self.departed_wait_minutes: list[float] = []
        self.boarded_persons = 0
        self.spawned_persons = 0
        self.spawned_persons_by_intent: Counter[str] = Counter()
        self.frames: list[dict[str, Any]] = []
        self.facility_service_events: list[FacilityServiceEvent] = []
        self._facility_service_event_id = 0
        self.snapshot_builder = SnapshotBuilder()
        self.audit = AuditLogger(
            enabled=scenario.audit_enabled,
            print_events=scenario.audit_print_events,
        )
        self.jupedsim = JuPedSimAdapter()
        self.movement_backend = movement_backend or self._build_movement_backend()
        self.progress_monitor = ProgressMonitor()
        if scenario.station_design is None:
            raise ValueError(
                "StationDesignDocument is required. Pass station_design or use "
                "--design-template in the CLI."
            )
        self.layout_graph = DesignCompiler.compile(scenario.station_design, scenario)
        self.facility_choice_policy = (
            facility_choice_policy
            if facility_choice_policy is not None
            else StaffGuidedPolicy()
            if scenario.admin_agent_count > 0
            else DefaultFacilityChoicePolicy()
        )
        self.facilities = [facility_agent_for_spec(self, spec) for spec in self.layout_graph.facilities]
        self.facilities_by_id = {facility.facility_id: facility for facility in self.facilities}
        self.gates = self._facilities_for_stage(FacilityStage.ENTRY_GATE)
        self.gate = self._require_first(self.gates, "entry gate facility")
        self.exit_gates = self._facilities_for_stage(FacilityStage.EXIT_GATE)
        self.vertical_transports = self._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER)
        self.boarding_doors = self._facilities_for_stage(FacilityStage.BOARDING_DOOR)
        platform_descriptors = self.layout_graph.platform_descriptors()
        self.platforms = [
            PlatformAgent(
                self,
                platform_id=platform_id,
                line_id=line_id,
                direction=direction,
            )
            for platform_id, line_id, direction in platform_descriptors
        ]
        self.platforms_by_id = {platform.platform_id: platform for platform in self.platforms}
        self.platform = self._require_first(self.platforms, "platform descriptor")
        self.trains = [
            TrainAgent(
                self,
                platform_id=platform_id,
                line_id=line_id,
                direction=direction,
            )
            for platform_id, line_id, direction in platform_descriptors
        ]
        self.trains_by_platform_id = {train.platform_id: train for train in self.trains}
        self.train = self._require_first(self.trains, "train service")
        self.admin_agents = [
            AdminAgent(
                self,
                patrol_route=self._admin_patrol_route(index),
                guide_radius=scenario.admin_guide_radius_units,
            )
            for index in range(max(0, scenario.admin_agent_count))
        ]
        self._spatial_index: dict[tuple[int, int], list[PassengerAgent]] = {}
        self._spatial_cell_size = max(1.0, self.scenario.crowd_radius_units)
        self._jupedsim_walkable_area = None
        self._jupedsim_level_walkable_areas: dict[str, Any] = {}
        self.demand_scheduler = DemandScheduler.from_scenario(scenario, self.random)
        self.spawn_schedule = self.demand_scheduler.spawn_schedule
        self.alighting_schedule = self.demand_scheduler.alighting_schedule
        self.datacollector = mesa.DataCollector(
            model_reporters={
                "station_persons": station_persons,
                "gate_queue_persons": gate_queue_persons,
                "vertical_queue_persons": vertical_queue_persons,
                "platform_waiting_persons": platform_waiting_persons,
                "boarded_persons": lambda m: m.boarded_persons,
                "average_system_minutes": average_system_minutes,
                "crowding_index": crowding_index,
                "average_walk_speed_factor": average_walk_speed_factor,
            }
        )

    @property
    def current_time_seconds(self) -> float:
        return self.step_index * self.scenario.tick_seconds

    def _require_first(self, items: list[Any], label: str) -> Any:
        if items:
            return items[0]
        design_id = getattr(self.scenario.station_design, "id", "<unknown>")
        raise ValueError(f"Station design {design_id!r} must define at least one {label}")

    def next_facility_service_event_id(self) -> int:
        self._facility_service_event_id += 1
        return self._facility_service_event_id

    def record_facility_service_event(self, event: FacilityServiceEvent) -> None:
        self.facility_service_events.append(event)

    def passenger_has_active_facility_service(self, passenger: PassengerAgent) -> bool:
        facility_id = passenger.assigned_facility_id or passenger.current_goal.facility_id
        if facility_id is None:
            return False
        facility = self.facilities_by_id.get(facility_id)
        return bool(facility is not None and facility.has_active_service(passenger))

    def _build_movement_backend(self) -> MovementBackend:
        requested = self.scenario.movement_backend_name
        if requested in {"jupedsim", "batched_jupedsim"} and self.jupedsim.status.available:
            return BatchedJuPedSimMovementBackend(
                self.jupedsim,
                strict=self.scenario.jupedsim_strict,
            )
        if requested == "micro_jupedsim" and self.jupedsim.status.available:
            return JuPedSimMovementBackend(
                self.jupedsim,
                strict=self.scenario.jupedsim_strict,
            )
        if requested in {"jupedsim", "batched_jupedsim", "micro_jupedsim"}:
            raise RuntimeError(
                f"JuPedSim backend {requested!r} requested but unavailable: "
                f"{self.jupedsim.status.message}"
            )
        raise ValueError(
            f"Unsupported movement backend {requested!r}. "
            "Use 'jupedsim', 'batched_jupedsim', or 'micro_jupedsim'."
        )

    def _admin_patrol_route(self, index: int) -> list[tuple[float, float]]:
        station_graph = self.layout_graph.station_graph
        if station_graph is not None:
            ordered_nodes = [
                *station_graph.nodes_matching(facility_stage=FacilityStage.ENTRY_GATE.value),
                *station_graph.nodes_matching(facility_stage=FacilityStage.VERTICAL_TRANSFER.value),
                *station_graph.nodes_matching(kind="platform"),
            ]
            route = [node.position for node in ordered_nodes]
            if route:
                offset = index % len(route)
                return route[offset:] + route[:offset]

        geom = self.layout_graph.geometry
        return [geom.paid_hall_center, geom.vertical_decision_point, geom.platform_entry]

    def spawn_passengers(self) -> None:
        due_by_intent = self.demand_scheduler.due_by_intent(self.step_index)
        for intent, count in due_by_intent.items():
            for _ in range(count):
                self._spawn_passenger(intent)

    def spawn_alighting_passengers(self) -> None:
        due = self.demand_scheduler.due_alightings(self.step_index)
        if due <= 0:
            return

        boarding_trains = [train for train in self.trains if train.is_boarding]
        if not boarding_trains:
            self.audit.record(
                "alighting_demand_without_boarding_train",
                source="demand_scheduler",
                severity="warning",
                step=self.step_index,
                context={"due_persons": due},
            )
            return

        for train, count in zip(
            boarding_trains,
            self._split_count(due, len(boarding_trains)),
            strict=True,
        ):
            self._spawn_alighting_passengers_for_train(train, count)

    def _spawn_passenger(
        self,
        intent: str | AgentIntent,
        *,
        initial_position: tuple[float, float] | None = None,
        initial_level_id: str | None = None,
    ) -> PassengerAgent:
        passenger = PassengerAgent(
            self,
            group_size=self.scenario.group_size,
            created_step=self.step_index,
            intent=intent,
            initial_position=initial_position,
            initial_level_id=initial_level_id,
        )
        self.passengers.append(passenger)
        self.spawned_persons += passenger.group_size
        self.spawned_persons_by_intent[passenger.intent] += passenger.group_size
        return passenger

    def _spawn_alighting_passengers_for_train(self, train: TrainAgent, count: int) -> None:
        if count <= 0:
            return

        doors = self.boarding_doors_for_train(train)
        if not doors:
            self.audit.record(
                "alighting_train_has_no_doors",
                source="demand_scheduler",
                severity="error",
                step=self.step_index,
                context={
                    "train_id": train.unique_id,
                    "platform_id": train.platform_id,
                    "due_persons": count,
                },
            )
            return

        door_spawn_counts: Counter[str] = Counter()
        for index in range(count):
            door = doors[(index + self.step_index + train.departed_trains) % len(doors)]
            local_index = door_spawn_counts[door.facility_id]
            door_spawn_counts[door.facility_id] += 1
            passenger = self._spawn_passenger(
                AgentIntent.EXIT_STATION,
                initial_position=self._alighting_spawn_position(door, local_index),
                initial_level_id=door.spec.exit_level_id or door.spec.entry_level_id,
            )
            passenger.assigned_platform_id = train.platform_id
            passenger.assigned_line_id = train.line_id
            passenger.assigned_direction = train.direction

    def _alighting_spawn_position(
        self,
        door: FacilityProcessAgent,
        local_index: int,
    ) -> tuple[float, float]:
        base_x, base_y = door.spec.exit_position
        anchor_x, anchor_y = door.spec.queue_anchor
        inward_x = anchor_x - base_x
        inward_y = anchor_y - base_y
        length = hypot(inward_x, inward_y)
        if length <= 0.001:
            inward_x, inward_y = 0.0, -1.0
        else:
            inward_x /= length
            inward_y /= length

        side_x = -inward_y
        side_y = inward_x
        spacing = max(0.35, self.scenario.jupedsim_agent_radius_units * 2.2)
        lane = local_index % 4
        row = local_index // 4
        side_offset = (lane - 1.5) * spacing
        inward_offset = 0.35 + row * max(0.25, self.scenario.jupedsim_agent_radius_units * 1.8)
        raw = (
            base_x + inward_x * inward_offset + side_x * side_offset,
            base_y + inward_y * inward_offset + side_y * side_offset,
        )
        level_id = door.spec.exit_level_id or door.spec.entry_level_id
        try:
            return project_to_safe_point(
                self.jupedsim_walkable_area(level_id),
                self.clamp_position(raw),
                clearance=max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05),
                require_inside=False,
            )
        except Exception:
            return self.clamp_position(raw)

    def _split_count(self, count: int, buckets: int) -> list[int]:
        if buckets <= 0:
            return []
        base, remainder = divmod(max(0, count), buckets)
        return [base + (1 if index < remainder else 0) for index in range(buckets)]

    def plan_for_intent(self, intent) -> AgentPlan:
        station_graph = self.layout_graph.station_graph
        if station_graph is not None:
            return plan_for_station_graph(intent, station_graph)
        return AgentPlan.for_intent(intent)

    def _facilities_for_stage(self, stage: str | FacilityStage) -> list[FacilityProcessAgent]:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        return [facility for facility in self.facilities if facility.spec.stage == stage_value]

    def request_facility_choice(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> FacilityProcessAgent | None:
        """Choose the next facility through one policy hook."""

        facility = self._choose_facility_for_stage(passenger, stage)
        if facility is None:
            return None
        passenger.plan.assign_facility(facility.spec.stage, facility.facility_id)
        facility.join_queue(passenger)
        return facility

    def preselect_facility_choice(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> FacilityProcessAgent | None:
        facility = self._choose_facility_for_stage(passenger, stage)
        if facility is None:
            return None
        passenger.plan.assign_facility(facility.spec.stage, facility.facility_id)
        return facility

    def join_preselected_facility_queue(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> bool:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        facility_id = passenger.plan.chosen_facilities.get(stage_value)
        if facility_id is None:
            return False
        if facility_id in passenger.avoided_facility_ids_by_stage.get(stage_value, set()):
            return False
        facility = self.facilities_by_id.get(facility_id)
        if facility is None or facility.spec.stage != stage_value:
            return False
        if not facility.is_available_for_choice:
            return False
        facility.join_queue(passenger)
        return True

    def route_to_facility_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[tuple[float, float], ...]:
        level_id = facility.spec.entry_level_id or passenger.current_level_id
        target = self.clamp_position(facility.spec.queue_anchor)
        try:
            area = self.jupedsim_walkable_area(level_id)
            target = project_to_safe_point(
                area,
                target,
                clearance=max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05),
                require_inside=False,
            )
        except Exception:
            target = self.clamp_position(target)

        route = self._station_graph_route_to_facility(passenger, facility)
        return self._dedupe_route_points((*route, target))

    def _station_graph_route_to_facility(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[tuple[float, float], ...]:
        station_graph = getattr(self.layout_graph, "station_graph", None)
        if station_graph is None:
            return ()

        element_id = self._facility_element_id(facility.facility_id)
        target_nodes = [
            node
            for node_id in station_graph.node_ids_for_element(element_id)
            if (node := station_graph.nodes.get(node_id)) is not None
            and node.kind == "facility_entry"
            and node.facility_stage == facility.spec.stage
        ]
        if not target_nodes:
            return ()

        level_id = facility.spec.entry_level_id or passenger.current_level_id
        start_candidates = [
            node
            for node in station_graph.nodes.values()
            if level_id is None or node.level_id == level_id
        ]
        try:
            start_node = station_graph.nearest_node(passenger.pos, start_candidates or None)
            path = station_graph.shortest_path(
                start_node.node_id,
                {node.node_id for node in target_nodes},
                allowed_kinds={"walk"},
            )
        except ValueError:
            return ()
        if path is None:
            return ()
        return tuple(path.positions[1:] or path.positions)

    def _facility_element_id(self, facility_id: str) -> str:
        parts = facility_id.split(":")
        if len(parts) >= 2:
            return parts[1]
        return facility_id

    def _dedupe_route_points(
        self,
        points: tuple[tuple[float, float], ...],
    ) -> tuple[tuple[float, float], ...]:
        route: list[tuple[float, float]] = []
        for point in points:
            if route and hypot(route[-1][0] - point[0], route[-1][1] - point[1]) <= 0.001:
                continue
            route.append(point)
        return tuple(route)

    def _choose_facility_for_stage(
        self,
        passenger: PassengerAgent,
        stage: str | FacilityStage,
    ) -> FacilityProcessAgent | None:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        candidates = self._facilities_for_stage(stage_value)
        if not candidates:
            self.audit.record(
                "facility_stage_has_no_candidates",
                source="facility_choice",
                severity="error",
                step=self.step_index,
                context={
                    "stage": stage_value,
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "state": passenger.state,
                },
            )
            passenger.last_replan_reason = f"no_facility_candidates:{stage_value}"
            return None
        try:
            facility = self.facility_choice_policy.choose(self, passenger, stage_value, candidates)
        except ValueError as exc:
            self.audit.record(
                "facility_choice_failed",
                source="facility_choice",
                severity="error",
                step=self.step_index,
                context={
                    "stage": stage_value,
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "state": passenger.state,
                    "error": str(exc),
                },
            )
            passenger.last_replan_reason = f"facility_choice_failed:{stage_value}"
            return None
        return facility

    def join_platform(self, passenger: PassengerAgent) -> bool:
        platform = self.platform_for_passenger(passenger)
        if platform is None:
            return False
        platform.join_waiting(passenger)
        return True

    def choose_platform(self, passenger: PassengerAgent) -> PlatformAgent | None:
        candidates = filter_platforms_for_passenger(passenger, self.platforms)
        if not candidates:
            self.audit.record(
                "platform_choice_failed",
                source="platform_choice",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "target_line_id": passenger.target_line_id,
                    "target_direction": passenger.target_direction,
                },
            )
            passenger.last_replan_reason = "platform_choice_failed"
            return None
        platform = pick_least_loaded(candidates, self.random, lambda item: item.waiting_persons)
        passenger.assigned_platform_id = platform.platform_id
        passenger.assigned_line_id = platform.line_id
        passenger.assigned_direction = platform.direction
        self.audit.record(
            "platform_selected",
            source="platform_choice",
            severity="debug",
            step=self.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "platform_id": platform.platform_id,
                "line_id": platform.line_id,
                "direction": platform.direction,
            },
        )
        return platform

    def platform_for_passenger(self, passenger: PassengerAgent) -> PlatformAgent | None:
        if passenger.assigned_platform_id is not None:
            platform = self.platforms_by_id.get(passenger.assigned_platform_id)
            if platform is not None:
                return platform
            self.audit.record(
                "assigned_platform_missing",
                source="platform_choice",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "platform_id": passenger.assigned_platform_id,
                },
            )
            passenger.last_replan_reason = "assigned_platform_missing"
            return None

        filtered = self.platforms
        if passenger.assigned_line_id is not None:
            filtered = [
                platform
                for platform in filtered
                if platform.line_id == passenger.assigned_line_id
            ]
        if passenger.assigned_direction is not None:
            filtered = [
                platform
                for platform in filtered
                if platform.direction == passenger.assigned_direction
            ]
        if len(filtered) == 1:
            return filtered[0]

        self.audit.record(
            "platform_assignment_missing",
            source="platform_choice",
            severity="error",
            step=self.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "assigned_line_id": passenger.assigned_line_id,
                "assigned_direction": passenger.assigned_direction,
                "candidate_count": len(filtered),
            },
        )
        passenger.last_replan_reason = "platform_assignment_missing"
        return None

    def boarding_doors_for_platform(self, platform: PlatformAgent) -> list[FacilityProcessAgent]:
        return filter_boarding_doors_for_platform(platform, self.boarding_doors)

    def boarding_doors_for_train(self, train: TrainAgent) -> list[FacilityProcessAgent]:
        doors = [
            door
            for door in self.boarding_doors
            if door.spec.platform_id == train.platform_id
        ]
        if doors:
            return doors
        return [
            door
            for door in self.boarding_doors
            if door.spec.line_id == train.line_id and door.spec.direction == train.direction
        ]

    def train_for_platform(self, platform: PlatformAgent) -> TrainAgent | None:
        train = self.trains_by_platform_id.get(platform.platform_id)
        if train is not None:
            return train
        for candidate in self.trains:
            if candidate.line_id == platform.line_id and candidate.direction == platform.direction:
                return candidate
        return None

    def boarding_train_for_platform(self, platform: PlatformAgent) -> TrainAgent | None:
        train = self.train_for_platform(platform)
        if train is not None and train.is_boarding:
            return train
        return None

    def train_for_facility(self, facility: FacilityProcessAgent) -> TrainAgent | None:
        platform_id = facility.spec.platform_id
        if platform_id is not None:
            return self.trains_by_platform_id.get(platform_id)
        for train in self.trains:
            if (
                train.line_id == facility.spec.line_id
                and train.direction == facility.spec.direction
            ):
                return train
        return None

    def route_for_key(
        self,
        route_key: str | RouteKey,
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], ...]:
        key = route_key.value if isinstance(route_key, RouteKey) else str(route_key)
        try:
            route = self.layout_graph.route_for_key(key, passenger.pos, passenger)
        except ValueError as exc:
            self.audit.record(
                "route_planning_failed",
                source="route_planning",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "state": passenger.state,
                    "route_key": key,
                    "current_level_id": passenger.current_level_id,
                    "error": str(exc),
                },
            )
            passenger.last_replan_reason = f"route_planning_failed:{key}"
            return ()
        return self._disperse_route_targets(key, route, passenger)

    def _disperse_route_targets(
        self,
        route_key: str,
        route: tuple[tuple[float, float], ...],
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], ...]:
        if not route or route_key == RouteKey.CURRENT_POSITION.value:
            return route
        if self.layout_graph.station_graph is None:
            return route

        spread = max(0.25, min(0.75, self.scenario.jupedsim_target_radius_units * 1.35))
        dispersed: list[tuple[float, float]] = []
        for index, point in enumerate(route):
            dispersed.append(self._disperse_route_point(point, passenger, index, spread))
        return tuple(dispersed)

    def _disperse_route_point(
        self,
        point: tuple[float, float],
        passenger: PassengerAgent,
        index: int,
        spread: float,
    ) -> tuple[float, float]:
        local_domain = self.jupedsim_walkable_area().intersection(ShapelyPoint(point).buffer(1.8))
        if local_domain.is_empty:
            return point

        passenger_id = int(getattr(passenger, "unique_id", 0) or 0)
        seed = passenger_id * 1103515245 + index * 12345 + self.step_index * 97
        angle = (seed % 6283) / 1000.0
        radius = spread * (0.35 + 0.65 * ((seed // 6283) % 17) / 16.0)
        candidate = (
            point[0] + math_cos(angle) * radius,
            point[1] + math_sin(angle) * radius,
        )
        if not local_domain.covers(ShapelyPoint(candidate)):
            candidate = point
        return project_to_safe_point(
            local_domain,
            candidate,
            clearance=max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05),
            require_inside=False,
        )

    def complete_departure(self, passenger: PassengerAgent, *, boarded: bool = True) -> None:
        if passenger.state == AgentState.DEPARTED.value:
            return
        self.movement_backend.remove_passenger(passenger)
        self._remove_from_station_holding_areas(passenger)
        passenger.state = AgentState.DEPARTED.value
        passenger.boarded_step = self.step_index
        minutes = (self.step_index - passenger.created_step) * self.scenario.tick_seconds / 60.0
        self.departed_wait_minutes.append(minutes)
        if boarded:
            self.boarded_persons += passenger.group_size
        try:
            self.passengers.remove(passenger)
        except ValueError:
            self.audit.record(
                "passenger_remove_missing",
                source="mesa_model",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "state": passenger.state,
                    "boarded": boarded,
                },
            )
        passenger.remove()

    def _remove_from_station_holding_areas(self, passenger: PassengerAgent) -> None:
        for platform in self.platforms:
            platform.waiting = [waiting for waiting in platform.waiting if waiting is not passenger]
        for facility in self.facilities:
            facility.queue = [queued for queued in facility.queue if queued is not passenger]

    def active_passengers(self) -> list[PassengerAgent]:
        return [
            passenger
            for passenger in self.passengers
            if passenger.state != AgentState.DEPARTED.value
        ]

    def clamp_position(self, position: tuple[float, float]) -> tuple[float, float]:
        geom = self.layout_graph.geometry
        x, y = position
        return (
            max(1.0, min(geom.width - 1.0, x)),
            max(1.0, min(geom.height - 1.0, y)),
        )

    def jupedsim_walkable_area(self, level_id: str | None = None):
        if level_id is None:
            if self._jupedsim_walkable_area is not None:
                return self._jupedsim_walkable_area
            self._jupedsim_walkable_area = self.layout_graph.walkable_geometry
            return self._jupedsim_walkable_area

        if level_id in self._jupedsim_level_walkable_areas:
            return self._jupedsim_level_walkable_areas[level_id]

        station_graph = getattr(self.layout_graph, "station_graph", None)
        document = getattr(station_graph, "source_document", None)
        if document is None:
            area = self.jupedsim_walkable_area()
        else:
            area = level_walkable_geometry(
                document,
                level_id,
                self.layout_graph.walkable_geometry,
            )
            if area.is_empty:
                area = self.jupedsim_walkable_area()
        self._jupedsim_level_walkable_areas[level_id] = area
        return area

    def _rectangular_jupedsim_walkable_area(self):
        from shapely import Polygon

        geom = self.layout_graph.geometry
        return Polygon(
            [(0.0, 0.0), (geom.width, 0.0), (geom.width, geom.height), (0.0, geom.height)]
        )

    def vertical_transport_speed(self, passenger: PassengerAgent) -> float:
        transport_id = passenger.assigned_transport_id
        if transport_id is None or not (0 <= transport_id < len(self.vertical_transports)):
            return self.scenario.walk_units_per_tick
        return (
            self.vertical_transports[transport_id].spec.speed_units_per_tick
            or self.scenario.walk_units_per_tick
        )

    def rebuild_spatial_index(self) -> None:
        cells: defaultdict[tuple[int, int], list[PassengerAgent]] = defaultdict(list)
        cell_size = self._spatial_cell_size
        for passenger in self.passengers:
            if passenger.state == AgentState.DEPARTED.value:
                continue
            x, y = passenger.pos
            cells[(int(x // cell_size), int(y // cell_size))].append(passenger)
        self._spatial_index = dict(cells)

    def nearby_passengers(
        self,
        passenger: PassengerAgent,
        radius: float,
    ) -> list[tuple[PassengerAgent, float, float, float]]:
        px, py = passenger.pos
        nearby: list[tuple[PassengerAgent, float, float, float]] = []
        cell_size = self._spatial_cell_size
        cx = int(px // cell_size)
        cy = int(py // cell_size)
        cell_radius = max(1, int(radius // cell_size) + 1)
        candidates: list[PassengerAgent] = []
        for ix in range(cx - cell_radius, cx + cell_radius + 1):
            for iy in range(cy - cell_radius, cy + cell_radius + 1):
                candidates.extend(self._spatial_index.get((ix, iy), []))
        limit = self.scenario.interaction_sample_limit
        if len(candidates) > limit:
            candidates = self.random.sample(candidates, limit)

        for other in candidates:
            if other is passenger or other.state == AgentState.DEPARTED.value:
                continue
            ox, oy = other.pos
            dx = px - ox
            dy = py - oy
            dist = (dx * dx + dy * dy) ** 0.5
            if 0.001 < dist < radius:
                nearby.append((other, dx, dy, dist))
            elif dist <= 0.001:
                angle = self.random.random() * 6.283185307
                nearby.append((other, math_cos(angle), math_sin(angle), 0.001))
        return nearby

    def local_density_load(self, passenger: PassengerAgent) -> float:
        scenario = self.scenario
        load = 0.0
        for other, _dx, _dy, dist in self.nearby_passengers(passenger, scenario.crowd_radius_units):
            proximity_weight = (scenario.crowd_radius_units - dist) / scenario.crowd_radius_units
            group_weight = max(0.25, other.group_size / scenario.group_size)
            load += proximity_weight * group_weight
        return load

    def walk_speed_factor(self, passenger: PassengerAgent) -> float:
        scenario = self.scenario
        density_load = self.local_density_load(passenger)
        factor = 1.0 / (1.0 + scenario.density_slowdown_strength * density_load)
        return max(scenario.min_walk_speed_factor, min(1.0, factor))

    def crowding_index(self) -> float:
        active = self.active_passengers()
        if not active:
            return 0.0
        sample_size = min(len(active), self.scenario.crowding_sample_size)
        sample = self.random.sample(active, sample_size) if len(active) > sample_size else active
        return sum(self.local_density_load(passenger) for passenger in sample) / len(sample)

    def average_walk_speed_factor(self) -> float:
        moving = [
            passenger
            for passenger in self.active_passengers()
            if passenger.state in CROWD_INTERACTION_STATES
        ]
        if not moving:
            return 1.0
        sample_size = min(len(moving), self.scenario.crowding_sample_size)
        sample = self.random.sample(moving, sample_size) if len(moving) > sample_size else moving
        return sum(self.walk_speed_factor(passenger) for passenger in sample) / len(sample)

    def step(self) -> None:
        self.spawn_passengers()
        for train in self.trains:
            train.step()
        self.spawn_alighting_passengers()
        for gate in self.gates:
            gate.step()
        for gate in self.exit_gates:
            gate.step()
        for transport in self.vertical_transports:
            transport.step()
        for platform in self.platforms:
            platform.step()
        for door in self.boarding_doors:
            door.step(self.train_for_facility(door))
        for admin in self.admin_agents:
            admin.step()

        for passenger in self.passengers:
            self._recover_stale_choosing_state(passenger)

        self.rebuild_spatial_index()
        for passenger, movement_result in self.movement_backend.step_all(list(self.passengers)):
            reached = passenger.apply_movement_result(movement_result)
            passenger.advance_after_movement(reached)
        self.progress_monitor.observe(self, list(self.passengers))

        self.rebuild_spatial_index()
        self.datacollector.collect(self)
        self.frames.append(self.snapshot())
        self.step_index += 1
        if self._should_stop():
            self.running = False

    def _recover_stale_choosing_state(self, passenger: PassengerAgent) -> None:
        recovery_state_by_state = {
            AgentState.CHOOSING_GATE.value: AgentState.ENTERING_STATION.value,
            AgentState.CHOOSING_VERTICAL.value: AgentState.WALKING_TO_VERTICAL.value,
            AgentState.CHOOSING_EXIT_GATE.value: AgentState.WALKING_TO_EXIT_GATE.value,
        }
        recovery_state = recovery_state_by_state.get(passenger.state)
        if recovery_state is None:
            return

        stale_state = passenger.state
        passenger.state = recovery_state
        passenger.progress_age_seconds = 0.0
        passenger.last_replan_reason = f"stale_state_recovered:{stale_state}"
        self.audit.record(
            "stale_choosing_state_recovered",
            source="state_recovery",
            severity="warning",
            step=self.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "from_state": stale_state,
                "to_state": recovery_state,
            },
        )

    def _should_stop(self) -> bool:
        if self.step_index >= self.scenario.horizon_steps:
            return True
        return (
            self.step_index >= self.scenario.demand_steps
            and not self.passengers
            and not self._has_pending_alighting_demand()
        )

    def _has_pending_alighting_demand(self) -> bool:
        return any(
            step >= self.step_index and count > 0
            for step, count in self.alighting_schedule.items()
        )

    def run(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        self.running = True
        total_steps = int(self.scenario.horizon_steps)
        if progress_callback is not None:
            progress_callback(self.step_index, total_steps)
        while self.running:
            self.step()
            if progress_callback is not None:
                progress_callback(self.step_index, total_steps)
        self._finalize_facilities()
        return self.frames

    def _finalize_facilities(self) -> None:
        for facility in self.facilities:
            finalize = getattr(facility, "finalize", None)
            if not callable(finalize):
                continue
            finalize()
        if self.frames:
            self.frames[-1] = self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return self.snapshot_builder.build(self).to_dict()
