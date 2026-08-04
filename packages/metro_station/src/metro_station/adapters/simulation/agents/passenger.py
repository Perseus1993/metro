from __future__ import annotations

from collections.abc import Iterable
from math import hypot

import mesa
from shapely.geometry import Point as ShapelyPoint

from .base import MovableAgent
from ..facilities.process import FacilitySpec
from ..movement.native_facility_motion import NativeFacilityMotion
from ..movement.backend import MovementResult
from ..movement.passive_motion_speed import bounded_passive_speed_mps
from ..movement.cornering_speed import (
    corner_speed_limit_mps,
    transition_speed_limit_mps,
    turn_angle_radians,
)
from ..planning.plan import (
    PASSIVE_STATES,
    WALKING_STATES,
    AgentIntent,
    FacilityStage,
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


def _point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    """Minimum distance from a body centre to one continuous motion segment."""

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    ratio = max(0.0, min(1.0, projection))
    closest = (start[0] + dx * ratio, start[1] + dy * ratio)
    return hypot(point[0] - closest[0], point[1] - closest[1])


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
        initial_position: Point | None = None,
        initial_level_id: str | None = None,
    ) -> None:
        super().__init__(model)
        self.group_size = int(group_size)
        self.created_step = int(created_step)
        self.boarded_step: int | None = None
        self.intent = intent.value if isinstance(intent, AgentIntent) else str(intent)
        self.plan = self.model.plan_for_intent(intent)
        self.goal_runtime = self.model.goal_runtime_for_intent(intent)
        self._initial_position_override = initial_position
        self._initial_level_id_override = initial_level_id
        self.spawn_source_element_id: str | None = None
        self.assigned_facility_id: str | None = None
        self.assigned_platform_id: str | None = None
        self.assigned_line_id: str | None = None
        self.assigned_direction: str | None = None
        self.last_completed_facility_id: str | None = None
        self.last_completed_facility_position: Point | None = None
        self.last_completed_facility_event_id: str | None = None
        self.last_completed_facility_level_id: str | None = None
        self.target_line_id = target_line_id
        self.target_direction = target_direction
        self.current_level_id: str | None = initial_level_id
        self.evacuation_facility_path: tuple[str, ...] = ()
        self.evacuation_facility_path_cost_seconds: float | None = None
        self.evacuation_pending = False
        self.replan_attempts_by_stage: dict[str, int] = {}
        self.avoided_facility_ids_by_goal: dict[str, set[str]] = {}
        self.facility_approach_slots_by_stage: dict[str, int] = {}
        self.facility_approach_facility_ids_by_stage: dict[str, str] = {}
        self.decision_facility_ids_by_region: dict[str, tuple[str, ...]] = {}
        self.decision_target_by_region: dict[str, tuple[float, float]] = {}
        self.decision_preferred_facility_id_by_region: dict[str, str] = {}
        self.decision_reconsider_after_seconds_by_region: dict[str, float] = {}
        self.decision_holding_target_by_region: dict[str, tuple[float, float]] = {}
        self.last_replan_reason: str | None = None
        self.progress_age_seconds: float = 0.0
        self.passive_facility_service = False
        # Semantic level membership remains the entry floor during a vertical
        # service.  Physical trajectory analysis needs a distinct connector
        # layer so an in-transit body is not falsely collided with bodies on
        # either floor's 2-D projection.
        self.physical_motion_layer_id: str | None = None
        self.suppress_movement_step: int | None = None
        sampled_free_speed = self.model.random.gauss(
            self.model.scenario.jupedsim_desired_speed_mps,
            self.model.scenario.jupedsim_free_speed_std_mps,
        )
        self.free_walk_speed_mps = min(
            self.model.scenario.jupedsim_free_speed_max_mps,
            max(self.model.scenario.jupedsim_free_speed_min_mps, sampled_free_speed),
        )
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
        self.route_segment_start = self.pos
        self.corner_recovery_anchor: Point | None = None
        self.corner_recovery_speed_limit_mps: float | None = None
        self.last_walk_velocity_mps: Point = (0.0, 0.0)
        self.passive_layout_motion_step: int | None = None
        self.passive_layout_motion_target: Point | None = None
        self.passive_layout_motion_speed_mps: float | None = None
        self.passive_layout_committed_delta: Point | None = None
        self.native_facility_motion: NativeFacilityMotion | None = None
        self.native_facility_arrival_time_seconds: float | None = None
        self._pending_route_transition: tuple[
            tuple[Point, ...],
            str,
            str,
            str | None,
            str | FacilityStage | None,
        ] | None = None
        self.goal_command_region_id: str | None = None
        self.model.goal_coordinator.initialize(self)

    def _initial_position(self) -> Point:
        if self._initial_position_override is not None:
            if self._initial_level_id_override is not None:
                self.current_level_id = self._initial_level_id_override
            position = self.model.clamp_position(self._initial_position_override)
            walkable_area = getattr(self.model, "jupedsim_walkable_area", None)
            if self.current_level_id is None or not callable(walkable_area):
                return position
            return self.model.clamp_position(
                project_to_safe_point(
                    walkable_area(self.current_level_id),
                    position,
                    clearance=self._initial_jupedsim_clearance(),
                    require_inside=False,
                )
            )

        station_graph = getattr(self.model.layout_graph, "station_graph", None)
        if station_graph is not None:
            if self.intent in {
                AgentIntent.EXIT_STATION.value,
                AgentIntent.EVACUATE_STATION.value,
                AgentIntent.TRANSFER.value,
            }:
                platform_nodes = station_graph.nodes_matching(kind="platform")
                if platform_nodes:
                    node = self.model.random.choice(platform_nodes)
                    self.current_level_id = node.level_id
                    return self._sample_platform_start_position(node)
            entrance_nodes = station_graph.nodes_matching(kind="entrance")
            if entrance_nodes:
                node = self._select_entrance_node(entrance_nodes)
                self.spawn_source_element_id = node.element_id
                self.current_level_id = node.level_id
                return self._sample_graph_node_position(node)

        geom = self.model.layout_graph.geometry
        jitter = self.model.random.uniform(-1.8, 1.8)
        if self.intent in {
            AgentIntent.EXIT_STATION.value,
            AgentIntent.EVACUATE_STATION.value,
            AgentIntent.TRANSFER.value,
        }:
            self.current_level_id = geom.platform_level_id
            return self.model.clamp_position(
                (
                    geom.platform_entry[0],
                    geom.platform_entry[1] + jitter,
                )
            )
        entrance = self.model.random.choice(geom.entrances)
        self.current_level_id = geom.concourse_level_id
        return (
            entrance[0],
            max(5.0, min(geom.height - 5.0, entrance[1] + jitter)),
        )

    def _select_entrance_node(self, entrance_nodes):
        configured = dict(self.model.scenario.entry_entrance_weights)
        if not configured:
            return self.model.random.choice(entrance_nodes)
        weighted = [
            (node, float(configured.get(str(node.element_id), 0.0)))
            for node in sorted(entrance_nodes, key=lambda item: item.node_id)
        ]
        total = sum(weight for _, weight in weighted)
        draw = self.model.random.random() * total
        cumulative = 0.0
        for node, weight in weighted:
            cumulative += weight
            if draw <= cumulative:
                return node
        return weighted[-1][0]

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
                clearance=self._initial_jupedsim_clearance(),
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
                        clearance=self._initial_jupedsim_clearance(),
                        require_inside=False,
                    )
                )
            domain = local_domain
        minimum_body_distance = max(
            0.05,
            float(self.model.scenario.jupedsim_agent_radius_units) * 2.2,
        )
        existing_positions = tuple(
            (float(passenger.pos[0]), float(passenger.pos[1]))
            for passenger in self.model.passengers
            if passenger.current_level_id == node.level_id
        )
        for _attempt in range(512):
            candidate = self.model.clamp_position(
                sample_safe_point(
                    domain,
                    self.model.random,
                    clearance=self._initial_jupedsim_clearance(),
                )
            )
            if all(
                hypot(
                    candidate[0] - position[0],
                    candidate[1] - position[1],
                )
                >= minimum_body_distance - 1e-9
                for position in existing_positions
            ):
                return candidate
        raise RuntimeError(
            f"level {node.level_id!r} has no collision-free initial spawn cell "
            f"within the local domain around node {node.node_id!r}"
        )

    def _initial_jupedsim_clearance(self) -> float:
        """Match the native adapter's admissible body-centre safe core."""

        return max(
            0.02,
            float(self.model.scenario.jupedsim_agent_radius_units) * 1.05,
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
        self.set_route(
            (target,),
            goal_kind=goal_kind,
            goal_label=goal_label,
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
        original_route = list(points)
        if not original_route:
            return
        normalized_stage = (
            stage.value if isinstance(stage, FacilityStage) else None if stage is None else str(stage)
        )
        if self._route_command_is_idempotent_reassertion(
            original_route,
            goal_kind=goal_kind,
            goal_label=goal_label,
            facility_id=facility_id,
            stage=normalized_stage,
        ):
            return
        route = list(original_route)
        while route and hypot(
            route[0][0] - self.pos[0],
            route[0][1] - self.pos[1],
        ) <= 1e-9:
            route.pop(0)
        if not route:
            self._pending_route_transition = None
            self.route = []
            self.target = original_route[-1]
            self.route_segment_start = self.pos
            self.corner_recovery_anchor = None
            self.corner_recovery_speed_limit_mps = None
            self.plan.set_goal(
                kind=goal_kind,
                label=goal_label,
                target=self.target,
                facility_id=facility_id,
                stage=stage,
            )
            return
        previous_segment_length = hypot(
            self.target[0] - self.route_segment_start[0],
            self.target[1] - self.route_segment_start[1],
        )
        previous_speed = hypot(*self.last_walk_velocity_mps)
        if previous_segment_length > 0.1 or previous_speed > 0.05:
            angle = turn_angle_radians(
                self.route_segment_start,
                self.pos,
                route[0],
            )
            base_speed = float(
                getattr(
                    self,
                    "free_walk_speed_mps",
                    self.model.scenario.jupedsim_desired_speed_mps,
                )
            )
            self.corner_recovery_anchor = self.pos
            transition_limit = transition_speed_limit_mps(
                self.last_walk_velocity_mps,
                (route[0][0] - self.pos[0], route[0][1] - self.pos[1]),
                base_speed,
                self.model.scenario,
            )
            if transition_limit is None:
                self._pending_route_transition = (
                    tuple(route),
                    goal_kind,
                    goal_label,
                    facility_id,
                    stage,
                )
                # Keep the previous physical direction for one movement
                # interval and brake before activating a mathematically
                # infeasible new-direction velocity.
                self.corner_recovery_anchor = self.pos
                self.corner_recovery_speed_limit_mps = 0.001
                return
            self.corner_recovery_speed_limit_mps = min(
                float(self.model.scenario.cornering_unknown_transition_speed_mps),
                corner_speed_limit_mps(base_speed, angle, self.model.scenario),
                transition_limit,
            )
        else:
            self.corner_recovery_anchor = None
            self.corner_recovery_speed_limit_mps = None
        self._pending_route_transition = None
        self.route_segment_start = self.pos
        self.target = route[0]
        self.route = route[1:]
        self.plan.set_goal(
            kind=goal_kind,
            label=goal_label,
            target=self.target,
            facility_id=facility_id,
            stage=stage,
        )

    def _route_command_is_idempotent_reassertion(
        self,
        route: list[Point],
        *,
        goal_kind: str,
        goal_label: str,
        facility_id: str | None,
        stage: str | None,
    ) -> bool:
        pending = self._pending_route_transition
        if pending is not None:
            pending_route, pending_kind, pending_label, pending_facility, pending_stage = pending
            pending_stage_value = (
                pending_stage.value
                if isinstance(pending_stage, FacilityStage)
                else None
                if pending_stage is None
                else str(pending_stage)
            )
            if (
                pending_kind == goal_kind
                and pending_label == goal_label
                and pending_facility == facility_id
                and pending_stage_value == stage
                and self._same_route(pending_route, route)
            ):
                return True

        goal = self.current_goal
        return (
            goal.kind == goal_kind
            and goal.label == goal_label
            and goal.facility_id == facility_id
            and goal.stage == stage
            and self._same_route((self.target, *self.route), route)
        )

    @staticmethod
    def _same_route(
        left: tuple[Point, ...] | list[Point],
        right: tuple[Point, ...] | list[Point],
    ) -> bool:
        return len(left) == len(right) and all(
            hypot(a[0] - b[0], a[1] - b[1]) <= 1e-6
            for a, b in zip(left, right, strict=True)
        )

    def _finish_current_target(self, *, snap_to_target: bool = True) -> bool:
        if snap_to_target:
            self.pos = self.target
        if self.route:
            corner = self.target
            next_target = self.route.pop(0)
            angle = turn_angle_radians(
                self.route_segment_start,
                corner,
                next_target,
            )
            base_speed = float(
                getattr(
                    self,
                    "free_walk_speed_mps",
                    self.model.scenario.jupedsim_desired_speed_mps,
                )
            )
            limit = corner_speed_limit_mps(base_speed, angle, self.model.scenario)
            if limit < base_speed:
                self.corner_recovery_anchor = corner
                self.corner_recovery_speed_limit_mps = limit
            else:
                self.corner_recovery_anchor = None
                self.corner_recovery_speed_limit_mps = None
            self.route_segment_start = corner
            self.target = next_target
            self._sync_goal_target()
            return False
        return True

    def move_toward_target(self) -> bool:
        return self.apply_movement_result(self.model.movement_backend.move(self))

    def move_directly_toward_target(
        self,
        max_distance: float | None = None,
        *,
        occupied_positions: Iterable[Point] = (),
        min_clearance: float | None = None,
    ) -> bool:
        """Advance a passive layout, using the physical backend when available."""
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
        backend = self.model.movement_backend
        owns_passive_motion = getattr(backend, "owns_passive_layout_motion", None)
        if callable(owns_passive_motion) and owns_passive_motion():
            # Queue compaction and platform waiting are physical pedestrian
            # motion, not presentation layout.  Defer the displacement to the
            # same persistent JuPedSim session that owns walking, while the
            # process layer continues to own the desired slot.
            tick_seconds = max(float(self.model.scenario.tick_seconds), 1e-9)
            desired_speed = float(
                getattr(self.model.scenario, "jupedsim_desired_speed_mps", 1.2)
            )
            self.request_passive_layout_motion(
                tuple(self.target),
                requested_speed_mps=min(
                    desired_speed,
                    max(0.0, float(step)) / tick_seconds,
                ),
            )
            return False
        if step <= 0.0 or distance <= max(step, self.model.scenario.jupedsim_target_radius_units):
            candidate = self._project_direct_layout_position(self.target)
            clear_candidate = self._clear_direct_layout_position(
                candidate,
                occupied_positions,
                min_clearance=min_clearance,
            )
            self.pos = clear_candidate
            if hypot(clear_candidate[0] - candidate[0], clear_candidate[1] - candidate[1]) > 0.001:
                return False
            return self._finish_current_target()

        ratio = step / distance
        candidate = self._project_direct_layout_position(
            (
                x + (tx - x) * ratio,
                y + (ty - y) * ratio,
            )
        )
        self.pos = self._clear_direct_layout_position(
            candidate,
            occupied_positions,
            min_clearance=min_clearance,
        )
        return False

    def request_passive_layout_motion(
        self,
        target: Point,
        *,
        requested_speed_mps: float,
    ) -> None:
        """Publish one acceleration- and endpoint-bounded native request."""

        tx, ty = float(target[0]), float(target[1])
        scenario = self.model.scenario
        tick_seconds = max(float(scenario.tick_seconds), 1e-9)
        observation_seconds = float(
            getattr(scenario, "movement_trace_sample_seconds", tick_seconds)
        )
        current_velocity = getattr(self, "last_walk_velocity_mps", (0.0, 0.0))
        current_speed = hypot(
            float(current_velocity[0]),
            float(current_velocity[1]),
        )
        acceleration_limit = float(
            getattr(scenario, "cornering_acceleration_limit_m_s2", 3.2)
        )
        desired_speed = float(
            getattr(scenario, "jupedsim_desired_speed_mps", 1.2)
        )
        transition_limit = transition_speed_limit_mps(
            (float(current_velocity[0]), float(current_velocity[1])),
            (tx - self.pos[0], ty - self.pos[1]),
            min(desired_speed, float(requested_speed_mps)),
            scenario,
            acceleration_window_s=observation_seconds,
        )
        published_target = (tx, ty)
        if transition_limit is None and current_speed > 1e-9:
            direction_bounded_speed = 0.001
            published_target = (float(self.pos[0]), float(self.pos[1]))
        else:
            direction_bounded_speed = (
                0.001 if transition_limit is None else transition_limit
            )
        published_distance = hypot(
            published_target[0] - self.pos[0],
            published_target[1] - self.pos[1],
        )
        self.passive_layout_motion_step = int(self.model.step_index)
        self.passive_layout_motion_target = published_target
        scalar_bounded_speed = bounded_passive_speed_mps(
            distance_m=published_distance,
            requested_speed_mps=direction_bounded_speed,
            current_speed_mps=current_speed,
            control_interval_s=tick_seconds,
            observation_interval_s=observation_seconds,
            acceleration_limit_m_s2=acceleration_limit,
        )
        # The scalar endpoint planner assumes one direction.  At a direction
        # change the vector transition budget is authoritative and may
        # require a lower speed than the scalar deceleration floor.
        self.passive_layout_motion_speed_mps = min(
            scalar_bounded_speed,
            direction_bounded_speed,
        )

    def _clear_direct_layout_position(
        self,
        candidate: Point,
        occupied_positions: Iterable[Point],
        *,
        min_clearance: float | None = None,
    ) -> Point:
        occupied = tuple(occupied_positions)
        clearance = (
            self._direct_layout_min_clearance()
            if min_clearance is None
            else max(0.0, float(min_clearance))
        )
        if self._has_direct_layout_clearance(candidate, occupied, clearance):
            return candidate

        x, y = self.pos
        for fraction in (0.75, 0.5, 0.25, 0.0):
            adjusted = self._project_direct_layout_position(
                (
                    x + (candidate[0] - x) * fraction,
                    y + (candidate[1] - y) * fraction,
                )
            )
            if self._has_direct_layout_clearance(adjusted, occupied, clearance):
                return adjusted
        return self.pos

    def _has_direct_layout_clearance(
        self,
        candidate: Point,
        occupied_positions: tuple[Point, ...],
        min_clearance: float,
    ) -> bool:
        for other in occupied_positions:
            if (
                _point_to_segment_distance(other, self.pos, candidate)
                < min_clearance - 1e-9
            ):
                return False
        return True

    def _direct_layout_min_clearance(self) -> float:
        scenario = self.model.scenario
        return max(
            0.05,
            float(scenario.jupedsim_agent_radius_units)
            * float(scenario.jupedsim_clearance_multiplier),
        )

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
        tick_seconds = max(1e-9, float(self.model.scenario.tick_seconds))
        self.last_walk_velocity_mps = (
            (float(result.position[0]) - float(self.pos[0])) / tick_seconds,
            (float(result.position[1]) - float(self.pos[1])) / tick_seconds,
        )
        self.pos = self.model.clamp_position(result.position)
        pending_transition = self._pending_route_transition
        if pending_transition is not None:
            self._pending_route_transition = None
            route, goal_kind, goal_label, facility_id, stage = pending_transition
            self.set_route(
                route,
                goal_kind=goal_kind,
                goal_label=goal_label,
                facility_id=facility_id,
                stage=stage,
            )
            return False
        if not result.reached:
            return False
        # JuPedSim declares a waypoint reached inside its target radius.  The
        # returned coordinate is the physical truth; snapping it to the exact
        # waypoint here creates a hidden 0.2–0.45 m jump after the final
        # internal sample and a reverse jump when the next episode starts.
        return self._finish_current_target(snap_to_target=False)

    def enter_facility_queue(self, spec: FacilitySpec) -> None:
        self.passive_facility_service = False
        self.last_walk_velocity_mps = (0.0, 0.0)
        self._pending_route_transition = None
        self.corner_recovery_anchor = None
        self.corner_recovery_speed_limit_mps = None
        self.state = spec.queue_state
        self.assigned_facility_id = spec.facility_id
        if spec.entry_level_id is not None:
            self.current_level_id = spec.entry_level_id
        self.plan.set_goal(
            kind="queued",
            label=f"{spec.label} queue",
            target=spec.queue_anchor,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )
        self.model.goal_parity.record(
            self,
            stream="physical",
            kind="queue_joined",
            time_seconds=self.model.current_time_seconds,
            stage=spec.stage,
            facility_id=spec.facility_id,
        )

    def begin_facility_service(self, spec: FacilitySpec) -> None:
        # A queue-layout request may have been prepared earlier in the same
        # facility step.  Once service starts, the facility motion model owns
        # the passenger and that stale passive request must not be committed.
        self.passive_layout_motion_step = None
        self.passive_layout_motion_target = None
        self.passive_layout_motion_speed_mps = None
        self.native_facility_motion = None
        self.native_facility_arrival_time_seconds = None
        # Transfer physical ownership only when the facility process really
        # owns the service trajectory.  A persistent crowd backend owns
        # same-floor gate traversal end to end, so deleting that native body
        # here creates a collision-invisible interval before the next tick.
        backend = self.model.movement_backend
        retains_at_admission = getattr(
            backend,
            "retains_native_body_at_facility_admission",
            None,
        )
        owns_service_motion = getattr(
            backend,
            "owns_continuous_facility_service_motion",
            None,
        )
        retained_by_backend = bool(
            (
                callable(retains_at_admission)
                and retains_at_admission(
                    facility_kind=str(spec.kind),
                    entry_level_id=spec.entry_level_id,
                )
            )
            or (
                callable(owns_service_motion)
                and owns_service_motion(
                    facility_kind=str(spec.kind),
                    entry_level_id=spec.entry_level_id,
                    exit_level_id=spec.exit_level_id,
                )
            )
        )
        if not retained_by_backend:
            # Stairs/escalators, elevator cabins, and train doors have their
            # own process authority.  Detach the former walking/waiting body;
            # it is reinserted at the authoritative release coordinate.
            backend.remove_passenger(self)
        self.passive_facility_service = False
        self.last_walk_velocity_mps = (0.0, 0.0)
        self._pending_route_transition = None
        self.state = spec.service_state
        self.assigned_facility_id = spec.facility_id
        if (
            spec.exit_level_id is not None
            and spec.stage != FacilityStage.VERTICAL_TRANSFER.value
        ):
            self.current_level_id = spec.exit_level_id
        self.set_route(
            spec.release_route,
            goal_kind="being_served",
            goal_label=spec.label,
            facility_id=spec.facility_id,
            stage=spec.stage,
        )
        self.model.goal_parity.record(
            self,
            stream="physical",
            kind="service_started",
            time_seconds=self.model.current_time_seconds,
            stage=spec.stage,
            facility_id=spec.facility_id,
        )
        self.model.goal_coordinator.service_started(self, spec.facility_id)

        if spec.platform_id is not None:
            self.assigned_platform_id = spec.platform_id
            self.assigned_line_id = spec.line_id
            self.assigned_direction = spec.direction

    def step(self) -> None:
        if (
            self.state in PASSIVE_STATES
            or self.state not in WALKING_STATES
            or self.movement_suppressed_this_step()
        ):
            return

        reached = self.move_toward_target()
        self.advance_after_movement(reached)

    def suppress_movement_for_current_step(self) -> None:
        self.suppress_movement_step = int(self.model.step_index)
        self.last_walk_velocity_mps = (0.0, 0.0)

    def movement_suppressed_this_step(self) -> bool:
        return self.suppress_movement_step == int(self.model.step_index)

    def advance_after_movement(self, reached: bool) -> None:
        """Apply the next plan action after a movement engine reaches a target."""
        if not reached:
            return

        self.model.goal_coordinator.movement_reached(self)
