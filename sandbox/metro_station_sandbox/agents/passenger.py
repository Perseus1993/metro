from __future__ import annotations

from math import hypot

import mesa
from shapely.geometry import Point as ShapelyPoint

from .base import MovableAgent
from ..facilities.process import FacilitySpec
from ..movement.backend import MovementResult
from ..planning.plan import (
    PASSIVE_STATES,
    WALKING_STATES,
    AgentIntent,
    FacilityStage,
    PlanAction,
    PlanActionKind,
)
from ..station.geometry import (
    document_walkable_geometry,
    element_shape,
    element_walkable_domain,
    level_walkable_geometry,
    project_to_safe_point,
    sample_safe_point,
)


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
        self.passive_facility_service = False
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
        sampled = self._sample_graph_node_position(node, local_radius=3.0)
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

    def _sample_graph_node_position(self, node, *, local_radius: float = 2.4) -> Point:
        station_graph = self.model.layout_graph.station_graph
        document = getattr(station_graph, "source_document", None)
        if document is None or node.element_id is None:
            return node.position

        element = document.element_by_id().get(node.element_id)
        if element is None:
            return node.position

        walkable = document_walkable_geometry(document)
        if element.kind == "walkable_area" or element.role == "floor":
            domain = element_walkable_domain(element, walkable)
        else:
            level_domain = level_walkable_geometry(document, node.level_id, walkable)
            local_domain = level_domain.intersection(
                element_shape(element.geometry).buffer(max(0.1, local_radius))
            )
            if local_domain.is_empty:
                local_domain = level_domain.intersection(
                    ShapelyPoint(node.position).buffer(max(0.1, local_radius))
                )
            if local_domain.is_empty:
                return self.model.clamp_position(
                    project_to_safe_point(
                        level_domain,
                        node.position,
                        clearance=self.model.scenario.jupedsim_agent_radius_units,
                        require_inside=False,
                    )
                )
            domain = local_domain
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

    def move_directly_toward_target(self, max_distance: float | None = None) -> bool:
        """Move passive layout states without invoking the crowd movement backend."""
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
            self.pos = self._project_direct_layout_position(self.target)
            return self._finish_current_target()

        ratio = step / distance
        self.pos = self._project_direct_layout_position(
            (
                x + (tx - x) * ratio,
                y + (ty - y) * ratio,
            )
        )
        return False

    def _project_direct_layout_position(self, position: Point) -> Point:
        candidate = self.model.clamp_position(position)
        try:
            domain = self.model.jupedsim_walkable_area(self.current_level_id)
        except Exception:
            return candidate
        if domain.covers(ShapelyPoint(candidate)):
            return candidate
        return self.model.clamp_position(
            project_to_safe_point(
                domain,
                candidate,
                clearance=self.model.scenario.jupedsim_agent_radius_units,
                require_inside=False,
            )
        )

    def apply_movement_result(self, result: MovementResult) -> bool:
        self.pos = self.model.clamp_position(result.position)
        if not result.reached:
            return False
        return self._finish_current_target()

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        self.model.movement_backend.remove_passenger(self)
        self.passive_facility_service = False
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
        self.model.movement_backend.remove_passenger(self)
        self.passive_facility_service = False
        self.state = spec.service_state
        self.plan.align_to_trigger_state(self.state)
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
        if self.state in PASSIVE_STATES or self.state not in WALKING_STATES:
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
