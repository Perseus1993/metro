from __future__ import annotations

from math import hypot

import mesa

from .base import MovableAgent, StationAgent
from ..planning.plan import (
    PASSIVE_STATES,
    AgentIntent,
    AgentState,
    FacilityStage,
    PlanAction,
    PlanActionKind,
)
from ..facilities.filters import filter_facilities_for_passenger
from ..facilities.process import FacilitySpec
from ..facilities.runtime import FacilityProcessAgent
from ..station.geometry import (
    document_walkable_geometry,
    element_walkable_domain,
    level_walkable_geometry,
    sample_safe_point,
)
from ..movement.backend import MovementResult
from ..planning.selection import pick_least_loaded


Point = tuple[float, float]


class PassengerAgent(MovableAgent):
    """Passenger group with explicit intent, plan, current goal, and state."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        group_size: int,
        created_step: int,
        intent: str | AgentIntent = AgentIntent.ENTER_AND_BOARD,
        target_line_id: str | None = None,
        target_direction: str | None = None,
    ) -> None:
        super().__init__(model)
        self.group_size = int(group_size)
        self.created_step = int(created_step)
        self.boarded_step: int | None = None
        self.intent = intent.value if isinstance(intent, AgentIntent) else str(intent)
        self.plan = self.model.plan_for_intent(intent)
        self.assigned_facility_id: str | None = None
        self.assigned_gate_id: int | None = None
        self.assigned_transport_id: int | None = None
        self.assigned_door_id: int | None = None
        self.assigned_platform_id: str | None = None
        self.assigned_line_id: str | None = None
        self.assigned_direction: str | None = None
        self.target_line_id = target_line_id
        self.target_direction = target_direction
        self.current_level_id: str | None = None
        self.replan_attempts_by_stage: dict[str, int] = {}
        self.avoided_facility_ids_by_stage: dict[str, set[str]] = {}
        self.last_replan_reason: str | None = None
        self.progress_age_seconds: float = 0.0
        preference_draw = self.model.random.random()
        self.prefers_elevator = preference_draw < self.model.scenario.elevator_preference_share
        self.prefers_stairs = (
            not self.prefers_elevator
            and preference_draw
            < self.model.scenario.elevator_preference_share
            + self.model.scenario.stairs_preference_share
        )
        self.state = self.plan.initial_state
        self.pos = self._initial_position()
        self.route: list[Point] = []
        self.target = self.pos
        self.set_route(
            self.model.route_for_key(self.plan.initial_route_key, self),
            goal_kind="walk",
            goal_label=self.plan.initial_goal_label,
        )

    def _initial_position(self) -> Point:
        station_graph = getattr(self.model.layout_graph, "station_graph", None)
        if station_graph is not None:
            if self.intent in {AgentIntent.EXIT_STATION.value, AgentIntent.TRANSFER.value}:
                platform_nodes = station_graph.nodes_matching(kind="platform")
                if platform_nodes:
                    node = self.model.random.choice(platform_nodes)
                    self.current_level_id = node.level_id
                    return self._sample_platform_start_position(node)
            entrance_nodes = station_graph.nodes_matching(kind="entrance")
            if entrance_nodes:
                node = self.model.random.choice(entrance_nodes)
                self.current_level_id = node.level_id
                return self._sample_graph_node_position(node)

        geom = self.model.layout_graph.geometry
        jitter = self.model.random.uniform(-1.8, 1.8)
        if self.intent in {AgentIntent.EXIT_STATION.value, AgentIntent.TRANSFER.value}:
            self.current_level_id = "B2"
            return self.model.clamp_position(
                (
                    geom.platform_entry[0],
                    geom.platform_entry[1] + jitter,
                )
            )
        entrance = self.model.random.choice(geom.entrances)
        self.current_level_id = "B1"
        return (
            entrance[0],
            max(5.0, min(geom.height - 5.0, entrance[1] + jitter)),
        )

    def _sample_platform_start_position(self, node) -> Point:
        sampled = self._sample_level_walkable_position(node.level_id)
        if sampled is not None:
            return sampled
        return self._sample_graph_node_position(node)

    def _sample_level_walkable_position(self, level_id: str) -> Point | None:
        station_graph = self.model.layout_graph.station_graph
        document = getattr(station_graph, "source_document", None)
        if document is None:
            return None

        walkable = document_walkable_geometry(document)
        domain = level_walkable_geometry(document, level_id, walkable)
        return self.model.clamp_position(
            sample_safe_point(
                domain,
                self.model.random,
                clearance=self.model.scenario.jupedsim_agent_radius_units,
            )
        )

    def _sample_graph_node_position(self, node) -> Point:
        if node.kind == "platform":
            return self.model.clamp_position(node.position)
        station_graph = self.model.layout_graph.station_graph
        document = getattr(station_graph, "source_document", None)
        if document is None or node.element_id is None:
            return node.position

        element = document.element_by_id().get(node.element_id)
        if element is None:
            return node.position

        walkable = document_walkable_geometry(document)
        domain = element_walkable_domain(element, walkable)
        return self.model.clamp_position(
            sample_safe_point(
                domain,
                self.model.random,
                clearance=self.model.scenario.jupedsim_agent_radius_units,
            )
        )

    @property
    def current_goal(self):
        return self.plan.current_goal

    def _sync_goal_target(self) -> None:
        goal = self.plan.current_goal
        self.plan.set_goal(
            kind=goal.kind,
            label=goal.label,
            target=self.target,
            facility_id=goal.facility_id,
            stage=goal.stage,
        )

    def set_target(
        self,
        target: Point,
        *,
        goal_kind: str = "walk",
        goal_label: str = "target",
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        self.route = []
        self.target = target
        self.plan.set_goal(
            kind=goal_kind,
            label=goal_label,
            target=target,
            facility_id=facility_id,
            stage=stage,
        )

    def set_route(
        self,
        points: list[Point] | tuple[Point, ...],
        *,
        goal_kind: str = "walk",
        goal_label: str = "route",
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        route = list(points)
        if not route:
            return
        self.target = route[0]
        self.route = route[1:]
        self.plan.set_goal(
            kind=goal_kind,
            label=goal_label,
            target=self.target,
            facility_id=facility_id,
            stage=stage,
        )

    def _finish_current_target(self) -> bool:
        self.pos = self.target
        if self.route:
            self.target = self.route.pop(0)
            self._sync_goal_target()
            return False
        return True

    def move_toward_target(self) -> bool:
        return self.apply_movement_result(self.model.movement_backend.move(self))

    def apply_movement_result(self, result: MovementResult) -> bool:
        self.pos = self.model.clamp_position(result.position)
        if not result.reached:
            return False
        return self._finish_current_target()

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        self.state = spec.queue_state
        self.assigned_facility_id = spec.facility_id
        if spec.entry_level_id is not None:
            self.current_level_id = spec.entry_level_id
        self.plan.assign_facility(spec.stage, spec.facility_id)
        self._assign_legacy_facility_index(spec)
        self.plan.set_goal(
            kind="queued",
            label=f"{spec.label} queue",
            target=spec.queue_anchor,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def begin_facility_service(self, spec: FacilitySpec) -> None:
        self.state = spec.service_state
        self.assigned_facility_id = spec.facility_id
        if spec.exit_level_id is not None:
            self.current_level_id = spec.exit_level_id
        self._assign_legacy_facility_index(spec)
        self.set_route(
            spec.release_route,
            goal_kind="being_served",
            goal_label=spec.label,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )

    def _assign_legacy_facility_index(self, spec: FacilitySpec) -> None:
        if spec.legacy_index is not None:
            if spec.stage == FacilityStage.ENTRY_GATE.value:
                self.assigned_gate_id = spec.legacy_index
            elif spec.stage == FacilityStage.VERTICAL_TRANSFER.value:
                self.assigned_transport_id = spec.legacy_index
            elif spec.stage == FacilityStage.BOARDING_DOOR.value:
                self.assigned_door_id = spec.legacy_index
        if spec.platform_id is not None:
            self.assigned_platform_id = spec.platform_id
            self.assigned_line_id = spec.line_id
            self.assigned_direction = spec.direction

    def step(self) -> None:
        if self.state in PASSIVE_STATES:
            return

        reached = self.move_toward_target()
        self.advance_after_movement(reached)

    def advance_after_movement(self, reached: bool) -> None:
        """Apply the next plan action after a movement engine reaches a target."""
        if not reached:
            return

        action = self.plan.action_for_reached_state(self.state)
        if action is not None:
            self._apply_plan_action(action)
            self.plan.advance_action(action)

    def _apply_plan_action(self, action: PlanAction) -> None:
        if action.completed_stage is not None:
            self.plan.complete_stage(action.completed_stage)
        if action.next_state is not None:
            self.state = action.next_state

        if action.kind == PlanActionKind.CHOOSE_FACILITY.value:
            if action.stage is None:
                raise ValueError(f"Plan action {action.label!r} is missing a facility stage")
            self.model.request_facility_choice(self, action.stage)
        elif action.kind == PlanActionKind.CHOOSE_PLATFORM.value:
            self.model.choose_platform(self)
            if action.route_key is not None:
                self.set_route(
                    self.model.route_for_key(action.route_key, self),
                    goal_kind="walk",
                    goal_label=action.label,
                )
        elif action.kind == PlanActionKind.WALK_ROUTE.value:
            if action.route_key is None:
                raise ValueError(f"Plan action {action.label!r} is missing a route key")
            self.set_route(
                self.model.route_for_key(action.route_key, self),
                goal_kind="walk",
                goal_label=action.label,
            )
        elif action.kind == PlanActionKind.JOIN_PLATFORM.value:
            self.model.join_platform(self)
        elif action.kind == PlanActionKind.DEPART.value:
            self.model.complete_departure(self, boarded=action.counts_boarded)


class TrainAgent(StationAgent):
    """A periodic train event with dwell and capacity constraints."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        line_id: str = "default",
        direction: str = "down",
        platform_id: str = "platform:default:down",
    ) -> None:
        super().__init__(model)
        scenario = self.model.scenario
        self.line_id = line_id
        self.direction = direction
        self.platform_id = platform_id
        self.state = "away"
        self.next_arrival_step = max(
            1, round(scenario.initial_train_offset_seconds / scenario.tick_seconds)
        )
        self.close_step: int | None = None
        self.current_load_persons = 0
        self.last_departed_load_persons = 0
        self.departed_trains = 0
        self.last_departure_step: int | None = None

    @property
    def is_boarding(self) -> bool:
        return self.state == "boarding"

    @property
    def capacity_remaining(self) -> int:
        return max(0, self.model.scenario.train_capacity_persons - self.current_load_persons)

    def step(self) -> None:
        scenario = self.model.scenario
        step = self.model.step_index

        if self.state == "away" and step >= self.next_arrival_step:
            self.state = "boarding"
            self.current_load_persons = 0
            self.close_step = step + max(
                1, round(scenario.train_dwell_seconds / scenario.tick_seconds)
            )
            return

        if self.state == "boarding" and self.close_step is not None and step >= self.close_step:
            self.state = "away"
            self.last_departed_load_persons = self.current_load_persons
            self.departed_trains += 1
            self.last_departure_step = step
            self.next_arrival_step = step + max(
                1, round(scenario.train_headway_seconds / scenario.tick_seconds)
            )
            self.close_step = None


class PlatformAgent(StationAgent):
    """Station platform resource agent that owns waiting and boarding."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        platform_id: str = "platform:default:down",
        line_id: str = "default",
        direction: str = "down",
    ) -> None:
        super().__init__(model)
        self.platform_id = platform_id
        self.line_id = line_id
        self.direction = direction
        self.state = "normal"
        self.waiting: list[PassengerAgent] = []

    @property
    def waiting_persons(self) -> int:
        return sum(passenger.group_size for passenger in self.waiting)

    @property
    def capacity_remaining(self) -> int:
        capacity = self.model.scenario.platform_capacity_persons
        door_queue = sum(
            door.queue_persons for door in self.model.boarding_doors_for_platform(self)
        )
        return max(0, capacity - self.waiting_persons - door_queue)

    def join_waiting(self, passenger: PassengerAgent) -> None:
        passenger.state = AgentState.WAITING_PLATFORM.value
        passenger.assigned_platform_id = self.platform_id
        passenger.assigned_line_id = self.line_id
        passenger.assigned_direction = self.direction
        passenger.plan.set_goal(
            kind="waiting",
            label="platform waiting area",
            target=passenger.pos,
        )
        if passenger not in self.waiting:
            self.waiting.append(passenger)

    def _layout_waiting(self) -> None:
        for index, passenger in enumerate(self.waiting):
            passenger.set_target(
                self.model.layout_graph.platform_waiting_position(index),
                goal_kind="waiting",
                goal_label="platform waiting slot",
            )
            passenger.move_toward_target()

    def _route_to_boarding_doors(self) -> None:
        for _ in range(self._boarding_release_limit()):
            if not self.waiting:
                break
            passenger = self.waiting.pop(0)
            self.model.request_facility_choice(passenger, FacilityStage.BOARDING_DOOR)

    def _boarding_release_limit(self) -> int:
        doors = self.model.boarding_doors_for_platform(self)
        if not doors:
            return 0

        per_door = max(
            1,
            int(self.model.scenario.platform_boarding_release_groups_per_door_tick),
        )
        frontage_limit = len(doors) * per_door
        available_slots = sum(
            max(0, self._door_queue_capacity(door) - len(door.queue)) for door in doors
        )
        if available_slots <= 0:
            return 0
        return min(len(self.waiting), frontage_limit, available_slots)

    def _door_queue_capacity(self, door: FacilityProcessAgent) -> int:
        slots = door.spec.queue_layout.slots
        if slots:
            return len(slots)
        return max(1, self.model.scenario.boarding_queue_slots_per_row * 2)

    def step(self) -> None:
        self._layout_waiting()
        if self.model.boarding_train_for_platform(self) is not None:
            self._route_to_boarding_doors()


class AdminAgent(MovableAgent):
    """Station staff agent that patrols and nudges passenger facility choices."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        patrol_route: list[Point] | tuple[Point, ...],
        guide_radius: float,
    ) -> None:
        super().__init__(model)
        route = list(patrol_route)
        if not route:
            route = [self.model.layout_graph.geometry.paid_hall_center]
        self.patrol_route = route
        self.guide_radius = float(guide_radius)
        self.patrol_index = 0
        self.guided_count = 0
        self.state = "patrolling"
        self.pos = route[0]
        self.target = route[1 % len(route)] if len(route) > 1 else route[0]

    def move_toward_target(self) -> bool:
        x, y = self.pos
        tx, ty = self.target
        dx = tx - x
        dy = ty - y
        dist = hypot(dx, dy)
        if dist <= 0.001:
            self.pos = self.target
            return True

        step = min(self.model.scenario.admin_patrol_speed_units_per_tick, dist)
        self.pos = self.model.clamp_position((x + dx / dist * step, y + dy / dist * step))
        return step >= dist

    def step(self) -> None:
        if self.move_toward_target():
            self.patrol_index = (self.patrol_index + 1) % len(self.patrol_route)
            self.target = self.patrol_route[(self.patrol_index + 1) % len(self.patrol_route)]
        self._guide_nearby_passengers()

    def _guide_nearby_passengers(self) -> None:
        policy = self.model.facility_choice_policy
        if not hasattr(policy, "guide_passenger"):
            return

        guided = 0
        for passenger in self.model.active_passengers():
            if (
                hypot(passenger.pos[0] - self.pos[0], passenger.pos[1] - self.pos[1])
                > self.guide_radius
            ):
                continue
            stage = self._next_facility_stage(passenger)
            if stage is None:
                continue
            facility = self._least_loaded_facility(passenger, stage)
            if facility is None:
                continue
            policy.guide_passenger(passenger.unique_id, facility.facility_id)
            guided += 1

        if guided:
            self.guided_count += guided
            self.model.audit.record(
                "admin_guided_passengers",
                source="admin_agent",
                severity="debug",
                count=guided,
                step=self.model.step_index,
                context={"admin_id": self.unique_id},
            )

    def _next_facility_stage(self, passenger: PassengerAgent) -> str | None:
        if passenger.plan.action_index >= len(passenger.plan.action_sequence):
            return None
        action = passenger.plan.action_sequence[passenger.plan.action_index]
        if (
            action.kind == PlanActionKind.CHOOSE_FACILITY.value
            and action.trigger_state == passenger.state
        ):
            return action.stage
        return None

    def _least_loaded_facility(self, passenger: PassengerAgent, stage: str):
        candidates = filter_facilities_for_passenger(
            passenger,
            stage,
            self.model._facilities_for_stage(stage),
        )
        if not candidates:
            return None
        return pick_least_loaded(
            candidates, self.model.random, lambda facility: facility.queue_persons
        )
