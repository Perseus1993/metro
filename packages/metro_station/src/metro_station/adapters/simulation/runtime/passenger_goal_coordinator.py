from __future__ import annotations

from dataclasses import replace
from math import hypot

from ..planning.goal_commands import GoalCommand, GoalCommandKind
from ..planning.goal_events import GoalEvent, GoalEventKind
from ..planning.goal_graph import GoalNodeKind
from ..planning.goal_state import FacilityInteractionState
from ..planning.plan import AgentIntent, AgentState, FacilityStage
from .decision_holding import PlatformWaitingCapacityError
from .evacuation_journey_rerouting import refresh_evacuation_facility_path
from .goal_event_ids import runtime_event_id
from .passenger_goal_command_executor import (
    ProductionGoalCommandContext,
    ProductionGoalCommandExecutor,
)
from .passenger_goal_service_observer import (
    ProductionGoalServiceEventObserver,
    ProductionServiceObservationContext,
)
from .passenger_goal_train_observer import PassengerGoalTrainObserver
from .service_chain_counters import (
    STALLED_PLATFORM_PARKING,
    WAITING_CAPACITY_RETRY,
    increment_service_chain_counter,
)
from .stalled_gate_ingress_recovery import advance_stalled_gate_ingress_turn


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

    def service_completed(self, passenger, facility_id: str, time_seconds: float) -> bool:
        return self._observe_service_fact(
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
    ) -> bool:
        state_before = passenger.goal_runtime.state
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
            return False
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
        event_was_processed = event.event_id in passenger.goal_runtime.state.processed_event_ids
        if (
            kind == GoalEventKind.SERVICE_COMPLETED
            and event_was_processed
            and passenger.assigned_facility_id == facility_id
        ):
            passenger.assigned_facility_id = None
        if kind == GoalEventKind.SERVICE_COMPLETED and not event_was_processed:
            (
                passenger.last_completed_facility_id,
                passenger.last_completed_facility_position,
                passenger.last_completed_facility_event_id,
                passenger.last_completed_facility_level_id,
            ) = previous_completion
        return passenger.goal_runtime.state != state_before

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
        if not changed and reason == "movement_stalled":
            changed = advance_stalled_gate_ingress_turn(
                self.model,
                passenger,
                reason=reason,
            ) or self._restore_stalled_committed_work(
                passenger,
                reason=reason,
            ) or self._reroute_stalled_region_approach(passenger, reason=reason)
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

    def _restore_stalled_committed_work(self, passenger, *, reason: str) -> bool:
        """Reissue retained physical work after a no-switch reassessment."""

        state = passenger.goal_runtime.state
        if state.commitment is None:
            return False
        command_kind = {
            FacilityInteractionState.APPROACH_QUEUE.value: (GoalCommandKind.WALK_TO_QUEUE.value),
            FacilityInteractionState.CAPTURE_QUEUE.value: (GoalCommandKind.JOIN_QUEUE.value),
        }.get(state.interaction_state)
        if command_kind is None:
            return False
        self._execute(
            passenger,
            (
                GoalCommand(
                    kind=command_kind,
                    goal_node_id=state.current_node_id,
                    stage=state.current_stage,
                    facility_id=state.commitment.facility_id,
                    reason=reason,
                ),
            ),
        )
        passenger.last_replan_reason = reason
        return True

    def _reroute_stalled_region_approach(self, passenger, *, reason: str) -> bool:
        """Recompute an uncommitted region route after a physical stall.

        ``PROGRESS_STALLED`` is a facility-choice event only after a
        commitment exists.  Before the decision region, the correct recovery
        is tactical: release any provisional portal/holding ownership and ask
        the physical router for a fresh path from the current native position.
        """

        state = passenger.goal_runtime.state
        node = passenger.goal_runtime.graph.node(state.current_node_id)
        if state.commitment is not None or self.model.passenger_has_active_facility_service(
            passenger
        ):
            return False
        active = self._active_decision_route(passenger, node, state)
        if active is None:
            return False
        region_id, stage = active
        before_replan = {
            "state": str(passenger.state),
            "position": [float(passenger.pos[0]), float(passenger.pos[1])],
            "target": [float(passenger.target[0]), float(passenger.target[1])],
            "route": [[float(point[0]), float(point[1])] for point in passenger.route],
            "holding_regions": sorted(passenger.decision_holding_target_by_region),
            "approach_facilities": dict(
                sorted(passenger.facility_approach_facility_ids_by_stage.items())
            ),
            "preferred_facility_id": (
                passenger.decision_preferred_facility_id_by_region.get(region_id)
            ),
        }
        router = self.executor.region_router
        base_region = router._base_region(region_id)
        platform_reservation = self.model._platform_waiting_reservations.get(
            int(passenger.unique_id)
        )
        if (
            base_region == "boarding_decision"
            and str(getattr(passenger, "intent", "")) == "enter_and_board"
        ):
            platform = self.model.platform_for_passenger(passenger)
            if platform is not None:
                if platform_reservation is None:
                    try:
                        self.model._reserve_platform_waiting_slot(
                            passenger,
                            platform,
                        )
                    except PlatformWaitingCapacityError:
                        increment_service_chain_counter(self.model, WAITING_CAPACITY_RETRY)
                    platform_reservation = self.model._platform_waiting_reservations.get(
                        int(passenger.unique_id)
                    )
                if platform_reservation is None:
                    platform = None
            if platform is not None:
                platform.join_waiting(passenger)
                increment_service_chain_counter(self.model, STALLED_PLATFORM_PARKING)
                if passenger.state == AgentState.WAITING_PLATFORM.value:
                    passenger.set_target(
                        tuple(passenger.pos),
                        goal_kind="waiting",
                        goal_label="stalled platform holding",
                    )
                passenger.last_replan_reason = reason
                self.model.audit.record(
                    "passenger_parked_stalled_platform_approach",
                    source="goal_runtime",
                    step=int(self.model.step_index),
                    context={
                        "passenger_id": int(passenger.unique_id),
                        "region_id": region_id,
                        "stage": stage,
                        "reason": reason,
                    },
                )
                return True
        # A finite holding or approach reservation is intentional
        # backpressure, not a stale route.  Releasing it on every crowd-induced
        # stall makes dense passengers synchronously reshuffle finite cells and
        # none keeps a stable route long enough to enter a newly freed
        # facility.  Preserve the owned target while recomputing the tactical
        # path; ``route`` can atomically exchange holding for approach as soon
        # as a facility becomes selectable.
        has_holding_reservation = base_region in passenger.decision_holding_target_by_region
        has_approach_reservation = (
            stage in passenger.facility_approach_slots_by_stage
            and stage in passenger.facility_approach_facility_ids_by_stage
        )
        if (
            has_approach_reservation
            and (
                passenger.last_replan_reason == reason
                or (
                    reason == "movement_stalled"
                    and base_region == "exit_gate_decision"
                )
            )
        ):
            self.model._clear_facility_targeting_reservation(passenger, stage)
            router.clear_decision_context(
                passenger,
                region_id,
                preserve_preference=False,
            )
            has_approach_reservation = False
        if not (has_holding_reservation or has_approach_reservation):
            # Platform storage is intentionally persistent while a passenger
            # waits for boarding capacity.  During an active region approach,
            # however, a movement-stalled body must be allowed to exchange an
            # unreachable reserved cell for a currently body-clear one.  The
            # exit-flow reservation remains untouched because it licenses
            # finite alighting admission upstream.
            if (
                base_region == "boarding_decision"
                and str(getattr(passenger, "intent", "")) == "enter_and_board"
            ):
                self.model._clear_platform_waiting_reservation(passenger)
            self.model._clear_all_facility_targeting_reservations(passenger)
            router.clear_decision_context(
                passenger,
                region_id,
                preserve_preference=False,
            )
        # Expose a narrow recovery scope while the route command reserves a
        # replacement platform cell; a persistent replan reason would also
        # change later, ordinary platform allocations.
        passenger._platform_waiting_stall_recovery = True
        passenger._force_least_loaded_stalled_replan = (
            base_region == "exit_gate_decision"
        )
        try:
            self._execute(
                passenger,
                (
                    GoalCommand(
                        kind=GoalCommandKind.WALK_TO_REGION.value,
                        goal_node_id=state.current_node_id,
                        stage=stage,
                        target_region_id=region_id,
                        reason=reason,
                    ),
                ),
            )
        finally:
            passenger._platform_waiting_stall_recovery = False
            passenger._force_least_loaded_stalled_replan = False
        if (
            base_region == "exit_gate_decision"
            and passenger.current_goal.kind == "goal_region"
            and not passenger.route
        ):
            target = tuple(passenger.target)
            if target != tuple(passenger.pos):
                passenger.set_route(
                    (target,),
                    goal_kind="goal_region",
                    goal_label=region_id,
                )
        passenger.last_replan_reason = reason
        commitment = state.commitment
        candidate_facility_ids = tuple(
            passenger.decision_facility_ids_by_region.get(base_region, ())
        )
        target_facility_id = (
            None if commitment is None else str(commitment.facility_id)
        )
        if target_facility_id is None:
            target_facility_id = passenger.assigned_facility_id
        if target_facility_id is None:
            target_facility_id = passenger.decision_preferred_facility_id_by_region.get(
                base_region
            )
        stage_order = {
            "entry_gate": 0,
            "vertical": 1,
            "exit_gate": 2,
            "boarding": 3,
        }

        def occupancy_for(facility) -> dict[str, object]:
            queue = getattr(facility, "queue", None)
            return {
                "facility_id": str(facility.facility_id),
                "stage": str(getattr(facility.spec.stage, "value", facility.spec.stage)),
                "queue_persons": 0 if queue is None else len(queue),
                "active_persons": len(getattr(facility, "active_passes", ())),
                "approach_reservations": (
                    0
                    if queue is None
                    else len(queue.approach_slot_reservations)
                ),
                "queue_capacity": int(
                    getattr(queue, "max_length", 0) or 0
                ),
                "forced_disabled": bool(getattr(facility, "is_forced_disabled", False)),
                "service_blocked_reason": getattr(
                    facility, "service_blocked_reason", None
                ),
            }

        facility_occupancy = [
            occupancy_for(facility)
            for facility in sorted(
                self.model.facilities,
                key=lambda item: str(item.facility_id),
            )
        ]
        current_stage_order = stage_order.get(str(stage), 0)
        upstream_occupancy = [
            item
            for item in facility_occupancy
            if stage_order.get(str(item["stage"]), current_stage_order)
            < current_stage_order
        ]
        downstream_occupancy = [
            item
            for item in facility_occupancy
            if stage_order.get(str(item["stage"]), current_stage_order)
            > current_stage_order
        ]
        self.model.audit.record(
            "passenger_replanned_stalled_region_approach",
            source="goal_runtime",
            step=int(self.model.step_index),
            context={
                "passenger_id": int(passenger.unique_id),
                "region_id": region_id,
                "stage": stage,
                "reason": reason,
                "before_replan": before_replan,
                "after_target": [float(passenger.target[0]), float(passenger.target[1])],
                "after_route": [[float(point[0]), float(point[1])] for point in passenger.route],
                "passenger_state": str(passenger.state),
                "goal_kind": str(passenger.current_goal.kind),
                "goal_node_id": state.current_node_id,
                "interaction_state": state.interaction_state,
                "target_facility_id": target_facility_id,
                "candidate_facility_ids": list(candidate_facility_ids),
                "upstream_occupancy": upstream_occupancy,
                "downstream_occupancy": downstream_occupancy,
                "facility_occupancy": facility_occupancy,
            },
        )
        return True

    def facility_unavailable(
        self,
        passenger,
        facility_id: str,
        *,
        reason: str,
    ) -> bool:
        """Invalidate a committed pre-service facility at the control boundary.

        A dynamic closure is a known environmental fact, not a progress-stall
        heuristic.  Sending the dedicated event lets the pure goal reducer
        clear the stale commitment and synchronously execute its queue cleanup
        before a replacement is selected.
        """

        before = passenger.goal_runtime.state
        event = GoalEvent(
            kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
            time_seconds=self.model.current_time_seconds,
            event_id=self._fact_id(passenger, "facility_unavailable", facility_id),
            stage=before.current_stage,
            facility_id=facility_id,
            reason=reason,
        )
        self.handle(passenger, event)
        after = passenger.goal_runtime.state
        handled = event.event_id in after.processed_event_ids
        if handled:
            self.model.goal_parity.record(
                passenger,
                stream="physical",
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=self.model.current_time_seconds,
                stage=before.current_stage,
                facility_id=facility_id,
                node_id=before.current_node_id,
                reason=reason,
            )
        return bool(handled and after.retry_count > before.retry_count)

    def poll(self, passenger) -> None:
        state = passenger.goal_runtime.state
        node = passenger.goal_runtime.graph.node(state.current_node_id)
        decision_route = self._active_decision_route(passenger, node, state)
        if decision_route is not None:
            region_id, stage = decision_route
            refreshed = self._refresh_stale_decision_route(
                passenger,
                region_id,
                stage,
            )
            if not refreshed and (
                passenger.current_goal.kind != "goal_region"
                or getattr(passenger, "goal_command_region_id", None) != region_id
            ):
                # A process-owned layout may replace the physical target
                # after the graph has already advanced to an ENTER_REGION
                # node. A still-valid decision context is not proof that its
                # WALK_TO_REGION command remains physically active.
                self._execute(
                    passenger,
                    (
                        GoalCommand(
                            kind=GoalCommandKind.WALK_TO_REGION.value,
                            goal_node_id=state.current_node_id,
                            stage=stage,
                            target_region_id=region_id,
                            reason="restore_missing_decision_route",
                        ),
                    ),
                )
            return
        if (
            state.interaction_state == FacilityInteractionState.APPROACH_QUEUE.value
            and state.commitment is not None
        ):
            # Process-owned waiting can temporarily replace the physical walk
            # target while the durable graph remains in APPROACH_QUEUE (for
            # example, when an active train-door crossing moves the next FIFO
            # owner to a safe platform cell). Reissue the idempotent approach
            # command so clearing that resource restores physical progress.
            self._execute(
                passenger,
                (
                    GoalCommand(
                        kind=GoalCommandKind.WALK_TO_QUEUE.value,
                        goal_node_id=state.current_node_id,
                        stage=state.current_stage,
                        facility_id=state.commitment.facility_id,
                    ),
                ),
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
            FacilityInteractionState.WAITING_CAPACITY.value,
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
            state.interaction_state == FacilityInteractionState.APPROACH_DECISION_REGION.value
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
    ) -> bool:
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
            return False
        router.clear_decision_context(
            passenger,
            region_id,
            preserve_preference=True,
        )
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
        return True

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
