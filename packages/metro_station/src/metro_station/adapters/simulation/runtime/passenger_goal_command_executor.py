from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

from ..facilities.process import FacilityKind
from ..facilities.runtime_base import FacilityProcessAgent
from ..planning.goal_commands import GoalCommand, GoalCommandKind
from ..planning.goal_events import GoalEvent, GoalEventKind
from ..planning.plan import AgentIntent, AgentState, FacilityStage
from .decision_holding import PlatformWaitingCapacityError
from .passenger_goal_observation import (
    ProductionGoalObservationAdapter,
    ProductionGoalObservationContext,
)
from .passenger_goal_region_router import PassengerGoalRegionRouter
from .service_chain_counters import (
    WAITING_CAPACITY_RETRY,
    increment_service_chain_counter,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class ProductionGoalCommandContext:
    model: MetroStationModel
    passenger: PassengerAgent


class ProductionGoalCommandExecutor:
    """Execute GoalCommands without making strategic choices."""

    def __init__(self) -> None:
        self.region_router = PassengerGoalRegionRouter()
        self.observation_adapter = ProductionGoalObservationAdapter(
            region_router=self.region_router,
        )

    def execute(
        self,
        context: ProductionGoalCommandContext,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]:
        del current_stage
        events: list[GoalEvent] = []
        for command in commands:
            events.extend(self._execute_one(context, command))
        return tuple(events)

    def _execute_one(
        self,
        context: ProductionGoalCommandContext,
        command: GoalCommand,
    ) -> tuple[GoalEvent, ...]:
        model = context.model
        passenger = context.passenger
        kind = GoalCommandKind(command.kind)
        if kind == GoalCommandKind.OBSERVE_CANDIDATES:
            return self._observe_candidates(context, command)
        if kind == GoalCommandKind.SELECT_FACILITY:
            return self._select_facility(model, passenger, command)
        if kind == GoalCommandKind.WALK_TO_REGION:
            return self._walk_to_region(model, passenger, command)
        if kind == GoalCommandKind.WALK_TO_QUEUE:
            return self._walk_to_queue(model, passenger, command)
        if kind == GoalCommandKind.JOIN_QUEUE:
            return self._join_queue(model, passenger, command)
        if kind == GoalCommandKind.REPLAN_STAGE:
            return self._replan(model, passenger, command)
        if kind == GoalCommandKind.WAIT_FOR_EVENT:
            goal_runtime = getattr(passenger, "goal_runtime", None)
            goal_state = getattr(goal_runtime, "state", None)
            if getattr(goal_state, "queued_facility_id", None) is not None:
                # A TRAIN_FULL observation does not transfer ownership back to
                # the platform.  The passenger keeps its FIFO place in the
                # boarding-door queue until a later train becomes available.
                return ()
            if command.event_kind == GoalEventKind.TRAIN_AVAILABLE.value and model.join_platform(
                passenger
            ):
                # Platform waiting is a physical resource with dispersed,
                # speed-limited slots. Registering here prevents successive
                # facility users from remaining colocated at a shared exit
                # portal while they wait for the next train.
                return ()
            if command.event_kind == GoalEventKind.TRAIN_AVAILABLE.value:
                passenger.state = AgentState.WAITING_PLATFORM.value
            if command.reason == "no_eligible_facility":
                # A stage-scoped approach reservation is already finite
                # downstream ownership.  Keep it across temporary capacity
                # waits (for example, between trains); clearing it here makes
                # the passenger compete for a smaller decision-holding pool
                # and breaks upstream backpressure.
                passenger.assigned_facility_id = None
                reservation = model._platform_waiting_reservations.get(int(passenger.unique_id))
                if reservation is not None:
                    platform = model.platform_for_passenger(passenger)
                    if platform is not None and passenger not in platform.waiting:
                        platform.waiting.append(passenger)
                    passenger.state = AgentState.WAITING_PLATFORM.value
                    passenger.set_target(
                        reservation.point,
                        goal_kind="waiting",
                        goal_label="platform waiting slot",
                    )
                elif self._hold_at_decision_region(model, passenger, command):
                    pass
                else:
                    passenger.state = AgentState.WAITING_CAPACITY.value
                    passenger.set_target(
                        tuple(passenger.pos),
                        goal_kind="waiting",
                        goal_label="facility capacity wait",
                    )
            # ``WAIT_FOR_EVENT`` is also the reducer's durable command for a
            # temporarily saturated or unavailable facility.  That wait keeps
            # the passenger at the physical decision/queue region and must not
            # transfer it into the unrelated platform waiting resource.
            return ()
        if kind == GoalCommandKind.COMPLETE_JOURNEY:
            model.complete_departure(
                passenger,
                boarded=passenger.intent
                in {AgentIntent.ENTER_AND_BOARD.value, AgentIntent.TRANSFER.value},
                goal_authorized=True,
            )
        return ()

    def _hold_at_decision_region(self, model, passenger, command: GoalCommand) -> bool:
        """Restore finite physical ownership while a facility stage is unavailable."""

        node_id = command.goal_node_id or passenger.goal_runtime.state.current_node_id
        node = passenger.goal_runtime.graph.node(node_id)
        region_id = node.decision_region_id
        if region_id is None:
            return False
        route = self.region_router.route(model, passenger, region_id)
        passenger.goal_command_region_id = None
        if self.region_router.reached(passenger, route):
            target = tuple(passenger.pos) if not route else tuple(route[-1])
            passenger.state = AgentState.WAITING_CAPACITY.value
            passenger.set_target(
                target,
                goal_kind="waiting",
                goal_label=f"{region_id} capacity holding",
            )
            return True
        passenger.state = self.region_router.walking_state(
            region_id=region_id,
            stage=command.stage,
        )
        passenger.set_route(
            route,
            goal_kind="decision_holding",
            goal_label=f"{region_id} capacity holding",
            stage=command.stage,
        )
        return True

    def _observe_candidates(
        self,
        context: ProductionGoalCommandContext,
        command: GoalCommand,
    ) -> tuple[GoalEvent, ...]:
        passenger = context.passenger
        event = self.observation_adapter.observe(
            ProductionGoalObservationContext(
                model=context.model,
                passenger=passenger,
                command=command,
            ),
            passenger.goal_runtime.graph,
            passenger.goal_runtime.state,
        )
        return () if event is None else (event,)

    def _select_facility(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        if command.selection_action == "retain":
            return ()
        facility = model.facilities_by_id.get(command.facility_id)
        event_time = self._event_time(model, passenger)
        if (
            not isinstance(facility, FacilityProcessAgent)
            or not facility.is_available_for_choice
            or not model.facility_has_reservable_approach_slot(passenger, facility)
        ):
            return (
                GoalEvent(
                    kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                    time_seconds=event_time,
                    event_id=self._event_id(command, "unavailable"),
                    command_id=command.command_id,
                    goal_node_id=command.goal_node_id,
                    stage=command.stage,
                    facility_id=command.facility_id,
                    reason="selection_execution_unavailable",
                ),
            )
        passenger.assigned_facility_id = facility.facility_id
        model._clear_vacated_decision_holding_reservations(passenger, schedule=True)
        if facility.spec.platform_id is not None:
            passenger.assigned_platform_id = facility.spec.platform_id
            passenger.assigned_line_id = facility.spec.line_id
            passenger.assigned_direction = model.facility_portal_binding(
                facility.facility_id
            ).direction
        model.control_timeline_controller.record_guided_selection(passenger, facility)
        model._reserve_facility_approach_slot(passenger, facility)
        return (
            GoalEvent(
                kind=GoalEventKind.FACILITY_SELECTED.value,
                time_seconds=event_time,
                event_id=self._event_id(command, "selected"),
                command_id=command.command_id,
                goal_node_id=command.goal_node_id,
                stage=facility.spec.stage,
                facility_id=facility.facility_id,
            ),
        )

    def _walk_to_region(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        region_id = str(command.target_region_id)
        route = self.region_router.route(model, passenger, region_id)
        passenger.goal_command_region_id = region_id
        passenger.state = self.region_router.walking_state(region_id=region_id)
        if self.region_router.reached(passenger, route):
            return (self._region_event(model, passenger, command, region_id),)
        passenger.set_route(route, goal_kind="goal_region", goal_label=region_id)
        return ()

    def _walk_to_queue(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        facility = model.facilities_by_id.get(command.facility_id)
        if not isinstance(facility, FacilityProcessAgent):
            return ()
        passenger.state = self.region_router.walking_state(stage=facility.spec.stage)
        if facility.spec.kind == FacilityKind.GATE.value:
            if (
                passenger.current_goal.kind == "queue_approach"
                and passenger.current_goal.label == "gate tail stall recovery"
                and passenger.current_goal.facility_id == facility.facility_id
            ):
                return ()
            # Every reserved owner may travel in parallel as far as the
            # lane-specific tail mouth, where collision dynamics form a
            # physical single-file queue. Capacity reservation order is not
            # service FIFO; the latter begins at physical mouth capture.
            if self._captures_queue_at_decision_boundary(model, passenger, facility):
                return (self._queue_capture_event(model, passenger, command, facility),)
            route = model.route_to_gate_queue_mouth(
                passenger,
                facility,
                passenger.facility_approach_slots_by_stage[facility.spec.stage],
            )
            passenger.route_waypoint_radius_override = None
            passenger.set_route(
                route,
                goal_kind="queue_approach",
                goal_label=f"{facility.spec.label} queue tail approach",
                facility_id=facility.facility_id,
                stage=facility.spec.stage,
            )
            return ()
        if self._keeps_active_queue_approach(model, passenger, facility):
            return ()
        if self._captures_queue_at_decision_boundary(model, passenger, facility):
            # Train-door portal arrivals and downstream exit-gate selections
            # capture FIFO ownership before walking through an occupied queue.
            # Queue layout motion then performs the ordered, clearance-checked
            # settling instead of letting a remote slot-0 approach reservation
            # pin an already-enqueued head at slot 1 or 2.
            return (self._queue_capture_event(model, passenger, command, facility),)
        route = model.route_to_facility_queue(passenger, facility)
        if model._passenger_near_facility_queue(passenger, facility) or not route:
            return (self._queue_capture_event(model, passenger, command, facility),)
        passenger.route_waypoint_radius_override = None
        passenger.set_route(
            route,
            goal_kind="queue_approach",
            goal_label=f"{facility.spec.label} queue approach",
            facility_id=facility.facility_id,
            stage=facility.spec.stage,
        )
        return ()

    def _join_queue(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        facility = model.facilities_by_id.get(command.facility_id)
        if not isinstance(facility, FacilityProcessAgent):
            return ()
        preferred_slot_index = None
        if command.stage is not None and (
            passenger.facility_approach_facility_ids_by_stage.get(command.stage)
            == facility.facility_id
        ):
            preferred_slot_index = passenger.facility_approach_slots_by_stage.get(command.stage)
        capture_at_decision_boundary = self._captures_queue_at_decision_boundary(
            model,
            passenger,
            facility,
        )
        if not capture_at_decision_boundary and preferred_slot_index is not None:
            preferred_target = model._facility_approach_slot_position(
                facility,
                preferred_slot_index,
            )
            if (
                hypot(
                    passenger.pos[0] - preferred_target[0],
                    passenger.pos[1] - preferred_target[1],
                )
                > model._facility_queue_capture_radius()
            ):
                if self._keeps_active_queue_approach(model, passenger, facility):
                    return ()
                route = model.route_to_facility_queue_slot(
                    passenger,
                    facility,
                    preferred_slot_index,
                )
                passenger.state = self.region_router.walking_state(stage=facility.spec.stage)
                passenger.route_waypoint_radius_override = None
                passenger.set_route(
                    route or (preferred_target,),
                    goal_kind="queue_approach",
                    goal_label=f"{facility.spec.label} queue approach",
                    facility_id=facility.facility_id,
                    stage=facility.spec.stage,
                )
                return ()
        if not facility.join_queue(
            passenger,
            authority="goal_graph",
            # Gate reservations certify finite approach capacity; physical
            # FIFO starts when bodies reach the common lane mouth. This avoids
            # a remote early claimant blocking a nearer body indefinitely.
            settle_after_walking=(
                not capture_at_decision_boundary or facility.spec.kind == FacilityKind.GATE.value
            ),
            preferred_slot_index=preferred_slot_index,
        ):
            if facility.spec.stage == FacilityStage.BOARDING_DOOR.value:
                self._restore_boarding_wait_after_join_block(
                    model,
                    passenger,
                    facility,
                )
            return ()
        if capture_at_decision_boundary:
            facility.queue.align_assigned_slots_with_fifo()
        if facility.spec.stage == FacilityStage.BOARDING_DOOR.value:
            model.leave_platform_waiting(passenger)
        if command.stage is not None:
            model._clear_vacated_facility_targeting_reservations(
                passenger,
                schedule_stage=command.stage,
            )
        model._clear_vacated_decision_holding_reservations(passenger, schedule=True)
        passenger.route_waypoint_radius_override = None
        return (
            GoalEvent(
                kind=GoalEventKind.QUEUE_JOINED.value,
                time_seconds=self._event_time(model, passenger),
                event_id=self._event_id(command, "queued"),
                command_id=command.command_id,
                goal_node_id=command.goal_node_id,
                stage=facility.spec.stage,
                facility_id=facility.facility_id,
            ),
        )

    @staticmethod
    def _restore_boarding_wait_after_join_block(model, passenger, facility) -> None:
        reservation = model._platform_waiting_reservations.get(int(passenger.unique_id))
        stage = FacilityStage.BOARDING_DOOR.value
        owns_approach = (
            passenger.facility_approach_facility_ids_by_stage.get(stage) == facility.facility_id
            and stage in passenger.facility_approach_slots_by_stage
        )
        if reservation is None and not owns_approach:
            return
        platform = model.platform_for_passenger(passenger)
        if reservation is None and platform is not None:
            try:
                target = model._reserve_platform_waiting_slot(passenger, platform)
            except PlatformWaitingCapacityError:
                increment_service_chain_counter(model, WAITING_CAPACITY_RETRY)
                # The passenger still owns a certified door-approach cell.
                # A failed queue join must not exchange that ownership for a
                # platform cell that does not exist. Retain the concrete
                # approach and retry when the crossing advances.
                target = model._facility_approach_slot_position(
                    facility,
                    passenger.facility_approach_slots_by_stage[stage],
                )
            else:
                if passenger not in platform.waiting:
                    platform.waiting.append(passenger)
            crossing_waiters = getattr(facility, "_crossing_waiting_passenger_ids", None)
            if crossing_waiters is not None:
                crossing_waiters.add(int(passenger.unique_id))
        elif reservation is not None:
            target = reservation.point
            if platform is not None and passenger not in platform.waiting:
                platform.waiting.append(passenger)
        else:
            target = model._facility_approach_slot_position(
                facility,
                passenger.facility_approach_slots_by_stage[stage],
            )
        passenger.state = AgentState.WAITING_PLATFORM.value
        passenger.set_target(
            target,
            goal_kind="waiting",
            goal_label="boarding queue capacity wait",
        )

    @staticmethod
    def _keeps_active_queue_approach(model, passenger, facility) -> bool:
        """Keep a live finite-slot route stable across durable command polls."""

        goal = passenger.current_goal
        stage = facility.spec.stage
        if (
            goal.kind != "queue_approach"
            or goal.facility_id != facility.facility_id
            or passenger.facility_approach_facility_ids_by_stage.get(stage) != facility.facility_id
        ):
            return False
        slot_index = passenger.facility_approach_slots_by_stage.get(stage)
        if slot_index is None:
            return False
        reserved_target = model._facility_approach_slot_position(
            facility,
            slot_index,
        )
        route_terminal = tuple(passenger.route[-1]) if passenger.route else tuple(passenger.target)
        return (
            hypot(
                route_terminal[0] - reserved_target[0],
                route_terminal[1] - reserved_target[1],
            )
            <= 1e-6
        )

    @staticmethod
    def _captures_queue_at_decision_boundary(model, passenger, facility) -> bool:
        if facility.spec.kind == FacilityKind.GATE.value:
            stage = facility.spec.stage
            if passenger.facility_approach_facility_ids_by_stage.get(stage) != facility.facility_id:
                return False
            slot_index = passenger.facility_approach_slots_by_stage.get(stage)
            if slot_index is None:
                return False
            ingress = model._gate_queue_ingress_anchors(
                passenger,
                facility,
                slot_index,
            )
            if not ingress:
                return False
            mouth = ingress[-1]
            capture_radius = max(
                model._facility_queue_capture_radius(),
                float(model.scenario.personal_space_units),
            )
            direct_distance = hypot(
                passenger.pos[0] - mouth[0],
                passenger.pos[1] - mouth[1],
            )
            swept_distance = _point_segment_distance(
                mouth,
                tuple(passenger.route_segment_start),
                tuple(passenger.pos),
            )
            return min(direct_distance, swept_distance) <= capture_radius
        if facility.spec.kind == FacilityKind.TRAIN_DOOR.value:
            owns_passive_motion = getattr(
                model.movement_backend,
                "owns_passive_layout_motion",
                None,
            )
            if not (callable(owns_passive_motion) and owns_passive_motion()):
                return False
            portal = model.facility_portal_binding(facility.facility_id).entry_point
            return (
                hypot(
                    passenger.pos[0] - portal[0],
                    passenger.pos[1] - portal[1],
                )
                <= model._facility_queue_capture_radius()
            )
        return False

    def _replan(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        facility = model.facilities_by_id.get(command.facility_id)
        if isinstance(facility, FacilityProcessAgent):
            facility.queue.discard(passenger)
        passenger.last_replan_reason = command.reason
        should_avoid = not str(command.reason or "").startswith("facility_disabled:")
        if should_avoid and command.goal_node_id is not None and command.facility_id is not None:
            passenger.avoided_facility_ids_by_goal.setdefault(
                command.goal_node_id,
                set(),
            ).add(command.facility_id)
        if command.stage is not None:
            model._clear_facility_targeting_reservation(passenger, command.stage)
        model._clear_all_decision_holding_reservations(passenger)
        passenger.assigned_facility_id = None
        if command.replan_cleanup_only:
            return ()
        observe = GoalCommand(
            kind=GoalCommandKind.OBSERVE_CANDIDATES.value,
            command_id=f"{command.command_id}:observe" if command.command_id else None,
            goal_node_id=command.goal_node_id,
            stage=command.stage,
        )
        return self._observe_candidates(
            ProductionGoalCommandContext(model=model, passenger=passenger),
            observe,
        )

    def _region_event(
        self,
        model,
        passenger,
        command: GoalCommand,
        region_id: str,
    ) -> GoalEvent:
        return GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=self._event_time(model, passenger),
            event_id=self._event_id(command, "region"),
            command_id=command.command_id,
            goal_node_id=command.goal_node_id,
            region_id=region_id,
        )

    def _queue_capture_event(
        self,
        model,
        passenger,
        command: GoalCommand,
        facility: FacilityProcessAgent,
    ) -> GoalEvent:
        return GoalEvent(
            kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
            time_seconds=self._event_time(model, passenger),
            event_id=self._event_id(command, "queue_capture"),
            command_id=command.command_id,
            goal_node_id=command.goal_node_id,
            stage=facility.spec.stage,
            facility_id=facility.facility_id,
        )

    def _event_id(self, command: GoalCommand, suffix: str) -> str | None:
        if command.command_id is None:
            return None
        return f"{command.command_id}:{suffix}"

    @staticmethod
    def _event_time(model, passenger) -> float:
        runtime = passenger.goal_runtime
        last_event_time = 0.0 if runtime is None else runtime.state.last_event_time_seconds
        return max(float(model.current_time_seconds), float(last_event_time))


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    segment = (end[0] - start[0], end[1] - start[1])
    length_squared = segment[0] * segment[0] + segment[1] * segment[1]
    if length_squared <= 1e-12:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = (
        (point[0] - start[0]) * segment[0] + (point[1] - start[1]) * segment[1]
    ) / length_squared
    projection = min(1.0, max(0.0, projection))
    closest = (
        start[0] + segment[0] * projection,
        start[1] + segment[1] * projection,
    )
    return hypot(point[0] - closest[0], point[1] - closest[1])
