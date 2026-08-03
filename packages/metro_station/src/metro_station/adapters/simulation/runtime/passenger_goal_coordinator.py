from __future__ import annotations

from dataclasses import replace
from math import hypot

from ..planning.goal_commands import GoalCommand, GoalCommandKind
from ..planning.goal_events import GoalEvent, GoalEventKind
from ..planning.goal_graph import GoalNodeKind
from ..planning.goal_state import FacilityInteractionState
from ..planning.plan import AgentIntent, FacilityStage
from .passenger_goal_command_executor import (
    ProductionGoalCommandContext,
    ProductionGoalCommandExecutor,
)
from .passenger_goal_train_observer import PassengerGoalTrainObserver
from .passenger_goal_service_observer import (
    ProductionGoalServiceEventObserver,
    ProductionServiceObservationContext,
)
from .goal_event_ids import runtime_event_id
from .evacuation_journey_rerouting import refresh_evacuation_facility_path


class PassengerGoalCoordinator:
    """Production event/command loop for active Goal Graph passengers."""

    def __init__(self, model) -> None:
        self.model = model
        self.executor = ProductionGoalCommandExecutor()
        self.train_observer = PassengerGoalTrainObserver()
        self.service_observer = ProductionGoalServiceEventObserver()
        self._command_sequences: dict[int, int] = {}

    def initialize(self, passenger) -> None:
        self._execute(passenger, passenger.goal_runtime.take_pending_commands())

    def movement_reached(self, passenger) -> None:
        goal = passenger.current_goal
        if goal.kind == "queue_approach" and goal.facility_id is not None:
            facility = self.model.facilities_by_id.get(goal.facility_id)
            if facility is None or not self.model._passenger_near_facility_queue(
                passenger,
                facility,
            ):
                return
            self.handle(
                passenger,
                GoalEvent(
                    kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                    time_seconds=self.model.current_time_seconds,
                    event_id=self._fact_id(passenger, "queue_capture", goal.facility_id),
                    stage=goal.stage,
                    facility_id=goal.facility_id,
                ),
            )
            return
        region_id = getattr(passenger, "goal_command_region_id", None)
        if goal.kind != "goal_region" or region_id is None:
            return
        if goal.target is None or hypot(
            passenger.pos[0] - goal.target[0],
            passenger.pos[1] - goal.target[1],
        ) > float(self.model.scenario.jupedsim_target_radius_units):
            return
        passenger.goal_command_region_id = None
        self.handle(
            passenger,
            GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=self.model.current_time_seconds,
                event_id=self._fact_id(passenger, "region", region_id),
                region_id=region_id,
            ),
        )

    def service_started(self, passenger, facility_id: str) -> None:
        self._observe_service_fact(
            passenger,
            GoalEventKind.SERVICE_STARTED,
            facility_id,
            self.model.current_time_seconds + self.model.scenario.tick_seconds,
        )

    def service_completed(self, passenger, facility_id: str, time_seconds: float) -> None:
        self._observe_service_fact(
            passenger,
            GoalEventKind.SERVICE_COMPLETED,
            facility_id,
            float(time_seconds),
        )

    def _observe_service_fact(
        self,
        passenger,
        kind: GoalEventKind,
        facility_id: str,
        time_seconds: float,
    ) -> None:
        event = self.service_observer.observe(
            ProductionServiceObservationContext(
                kind=kind,
                facility_id=facility_id,
                time_seconds=time_seconds,
                event_id=self._fact_id(passenger, kind.value, facility_id),
            ),
            passenger.goal_runtime.state,
        )
        if event is None:
            return
        previous_completion = (
            passenger.last_completed_facility_id,
            passenger.last_completed_facility_position,
            passenger.last_completed_facility_event_id,
            passenger.last_completed_facility_level_id,
        )
        if kind == GoalEventKind.SERVICE_COMPLETED:
            passenger.last_completed_facility_id = facility_id
            passenger.last_completed_facility_position = tuple(passenger.pos)
            passenger.last_completed_facility_event_id = event.event_id
            passenger.last_completed_facility_level_id = passenger.current_level_id
        self.handle(passenger, event)
        if (
            kind == GoalEventKind.SERVICE_COMPLETED
            and event.event_id not in passenger.goal_runtime.state.processed_event_ids
        ):
            (
                passenger.last_completed_facility_id,
                passenger.last_completed_facility_position,
                passenger.last_completed_facility_event_id,
                passenger.last_completed_facility_level_id,
            ) = previous_completion

    def replan(self, passenger, reason: str) -> bool:
        before = passenger.goal_runtime.state.retry_count
        state = passenger.goal_runtime.state
        facility_id = None if state.commitment is None else state.commitment.facility_id
        event = GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=self.model.current_time_seconds,
            event_id=self._fact_id(passenger, "replan", reason),
            stage=state.current_stage,
            facility_id=facility_id,
            reason=reason,
        )
        self.handle(passenger, event)
        changed = passenger.goal_runtime.state.retry_count > before
        if event.event_id in passenger.goal_runtime.state.processed_event_ids:
            self.model.goal_parity.record(
                passenger,
                stream="physical",
                kind=GoalEventKind.PROGRESS_STALLED.value,
                time_seconds=self.model.current_time_seconds,
                stage=state.current_stage,
                facility_id=facility_id,
                node_id=state.current_node_id,
                reason=reason,
            )
        return changed

    def poll(self, passenger) -> None:
        state = passenger.goal_runtime.state
        node = passenger.goal_runtime.graph.node(state.current_node_id)
        decision_route = self._active_decision_route(passenger, node, state)
        if decision_route is not None:
            region_id, stage = decision_route
            self._refresh_stale_decision_route(
                passenger,
                region_id,
                stage,
            )
            return
        if (
            state.interaction_state == FacilityInteractionState.CAPTURE_QUEUE.value
            and state.commitment is not None
        ):
            # A queue can legitimately reject admission while an earlier FIFO
            # reservation is still approaching or while the one-body-wide
            # physical order would be inverted.  Retry the idempotent command
            # from the durable graph state; the original movement-reached fact
            # must not be required to fire a second time.
            self._execute(
                passenger,
                (
                    GoalCommand(
                        kind=GoalCommandKind.JOIN_QUEUE.value,
                        goal_node_id=state.current_node_id,
                        stage=state.current_stage,
                        facility_id=state.commitment.facility_id,
                    ),
                ),
            )
            return
        if (
            node.kind == GoalNodeKind.WAIT_FOR_EVENT.value
            and node.wait_event_kind == GoalEventKind.TRAIN_AVAILABLE.value
        ):
            event = self.train_observer.waiting_event(self.model, passenger)
            if event is not None:
                self.handle(passenger, event)
            return
        if state.interaction_state in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            command = GoalCommand(
                kind="observe_candidates",
                goal_node_id=state.current_node_id,
                stage=state.current_stage,
                target_region_id=node.decision_region_id,
            )
            self._execute(passenger, (command,))
            return
        if (
            state.interaction_state == FacilityInteractionState.QUEUEING.value
            and state.current_stage == FacilityStage.BOARDING_DOOR.value
        ):
            event = self.train_observer.queued_event(self.model, passenger)
            if event is not None:
                self.handle(passenger, event)

    def _active_decision_route(self, passenger, node, state) -> tuple[str, str] | None:
        if (
            state.interaction_state
            == FacilityInteractionState.APPROACH_DECISION_REGION.value
            and node.decision_region_id is not None
            and state.current_stage is not None
        ):
            return node.decision_region_id, state.current_stage
        if node.kind != GoalNodeKind.ENTER_REGION.value or node.region_id is None:
            return None
        graph = passenger.goal_runtime.graph
        for transition in graph.outgoing(node.node_id):
            target = graph.node(transition.target_node_id)
            if (
                target.kind == GoalNodeKind.USE_FACILITY_STAGE.value
                and target.decision_region_id == node.region_id
                and target.facility_stage is not None
            ):
                return node.region_id, target.facility_stage
        return None

    def _refresh_stale_decision_route(
        self,
        passenger,
        region_id: str,
        stage: str,
    ) -> None:
        """Retarget an invalid tactical catchment before reaching its old portal."""

        if (
            stage == FacilityStage.VERTICAL_TRANSFER.value
            and passenger.intent == AgentIntent.EVACUATE_STATION.value
            and not self.model.passenger_has_active_facility_service(passenger)
        ):
            refresh_evacuation_facility_path(self.model, passenger)
        router = self.executor.region_router
        candidates = self.model._facilities_for_stage(stage)
        if not router.decision_context_needs_reroute(
            self.model,
            passenger,
            region_id,
            candidates,
        ):
            return
        router.clear_decision_context(passenger, region_id)
        self._execute(
            passenger,
            (
                GoalCommand(
                    kind=GoalCommandKind.WALK_TO_REGION.value,
                    goal_node_id=passenger.goal_runtime.state.current_node_id,
                    stage=stage,
                    target_region_id=region_id,
                    reason="decision_context_invalidated_en_route",
                ),
            ),
        )

    def handle(self, passenger, event: GoalEvent) -> None:
        event = self._monotonic_event(passenger, event)
        before = passenger.goal_runtime.state
        commands = passenger.goal_runtime.handle(event)
        self.model.goal_parity.record_graph_transition(
            passenger,
            event,
            before,
            passenger.goal_runtime.state,
        )
        self._execute(passenger, commands)

    def _execute(self, passenger, commands: tuple[GoalCommand, ...]) -> None:
        pending = list(commands)
        iterations = 0
        while pending:
            iterations += 1
            if iterations > 64:
                raise RuntimeError("goal command loop exceeded 64 immediate transitions")
            command = self._stamp(passenger, pending.pop(0))
            if command.kind == "select_facility":
                self._record_facility_choice(passenger, command)
                if command.selection_action != "retain":
                    self.model.goal_parity.record(
                        passenger,
                        stream="graph",
                        kind="facility_selected",
                        time_seconds=self.model.current_time_seconds,
                        stage=command.stage,
                        facility_id=command.facility_id,
                        node_id=command.goal_node_id,
                        reason=command.reason,
                    )
            if command.kind == "complete_journey":
                self.model.goal_parity.record(
                    passenger,
                    stream="graph",
                    kind="terminal_reached",
                    time_seconds=self.model.current_time_seconds,
                    node_id=command.goal_node_id,
                )
            events = self.executor.execute(
                ProductionGoalCommandContext(model=self.model, passenger=passenger),
                (command,),
                current_stage=passenger.goal_runtime.state.current_stage,
            )
            for event in events:
                event = self._monotonic_event(passenger, event)
                if event.kind == GoalEventKind.FACILITY_SELECTED.value:
                    self.model.goal_parity.record(
                        passenger,
                        stream="physical",
                        kind="facility_selected",
                        time_seconds=event.time_seconds,
                        stage=event.stage,
                        facility_id=event.facility_id,
                        node_id=event.goal_node_id,
                    )
                before = passenger.goal_runtime.state
                produced = passenger.goal_runtime.handle(event)
                self.model.goal_parity.record_graph_transition(
                    passenger,
                    event,
                    before,
                    passenger.goal_runtime.state,
                    skip_selection=True,
                )
                pending.extend(produced)

    def _monotonic_event(self, passenger, event: GoalEvent) -> GoalEvent:
        """Keep synchronous facts on the latest published interval boundary.

        Facility completion is observed inside the tick whose post-state is
        published at ``event.end_time``. Commands triggered synchronously by
        that fact can still consult services stamped at the interval start.
        They describe the same post-tick state and therefore inherit, rather
        than precede, the latest goal-event timestamp.
        """

        latest = float(passenger.goal_runtime.state.last_event_time_seconds)
        if event.time_seconds >= latest:
            return event
        return replace(event, time_seconds=latest)

    def _record_facility_choice(self, passenger, command: GoalCommand) -> None:
        evidence = dict(command.decision_evidence)
        record = {
            "passenger_id": int(passenger.unique_id),
            "time_seconds": float(self.model.current_time_seconds),
            "stage": command.stage,
            "goal_node_id": command.goal_node_id,
            "facility_id": command.facility_id,
            "action": command.selection_action or "select",
            "reason": command.reason,
            "decision": evidence,
        }
        self.model.facility_choice_decision_logs.append(record)
        self.model.audit.record(
            "facility_choice_decision",
            source="goal_runtime",
            step=int(self.model.step_index),
            context=record,
        )

    def _stamp(self, passenger, command: GoalCommand) -> GoalCommand:
        if command.command_id is not None:
            return command
        passenger_id = int(passenger.unique_id)
        sequence = self._command_sequences.get(passenger_id, 0) + 1
        self._command_sequences[passenger_id] = sequence
        state = passenger.goal_runtime.state
        return replace(
            command,
            command_id=f"p{passenger_id}:c{sequence}:{command.kind}",
            goal_node_id=command.goal_node_id or state.current_node_id,
            stage=command.stage or state.current_stage,
        )

    def _fact_id(self, passenger, kind: str, value: str) -> str:
        return runtime_event_id(
            passenger.unique_id,
            kind,
            value,
            self.model.current_time_seconds,
        )
