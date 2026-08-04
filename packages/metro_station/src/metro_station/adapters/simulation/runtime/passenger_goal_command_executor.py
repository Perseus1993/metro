from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..facilities.runtime_base import FacilityProcessAgent
from ..planning.goal_commands import GoalCommand, GoalCommandKind
from ..planning.goal_events import GoalEvent, GoalEventKind
from ..planning.plan import AgentIntent, AgentState, FacilityStage
from .passenger_goal_observation import (
    ProductionGoalObservationAdapter,
    ProductionGoalObservationContext,
)
from .passenger_goal_region_router import PassengerGoalRegionRouter

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
            if (
                command.event_kind == GoalEventKind.TRAIN_AVAILABLE.value
                and model.join_platform(passenger)
            ):
                # Platform waiting is a physical resource with dispersed,
                # speed-limited slots. Registering here prevents successive
                # facility users from remaining colocated at a shared exit
                # portal while they wait for the next train.
                return ()
            if command.event_kind == GoalEventKind.TRAIN_AVAILABLE.value:
                passenger.state = AgentState.WAITING_PLATFORM.value
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
        model._clear_all_decision_holding_reservations(passenger)
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
        route = model.route_to_facility_queue(passenger, facility)
        if model._passenger_near_facility_queue(passenger, facility) or not route:
            return (self._queue_capture_event(model, passenger, command, facility),)
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
            preferred_slot_index = passenger.facility_approach_slots_by_stage.get(
                command.stage
            )
        if not facility.join_queue(
            passenger,
            authority="goal_graph",
            settle_after_walking=True,
            preferred_slot_index=preferred_slot_index,
        ):
            return ()
        if facility.spec.stage == FacilityStage.BOARDING_DOOR.value:
            model.leave_platform_waiting(passenger)
        if command.stage is not None:
            model._clear_facility_targeting_reservation(passenger, command.stage)
        model._clear_all_decision_holding_reservations(passenger)
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

    def _replan(self, model, passenger, command: GoalCommand) -> tuple[GoalEvent, ...]:
        facility = model.facilities_by_id.get(command.facility_id)
        if isinstance(facility, FacilityProcessAgent):
            facility.queue.discard(passenger)
        passenger.last_replan_reason = command.reason
        should_avoid = not str(command.reason or "").startswith("facility_disabled:")
        if (
            should_avoid
            and command.goal_node_id is not None
            and command.facility_id is not None
        ):
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
