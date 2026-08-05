from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .choice import GoalFacilitySelector, MinimumPerceivedCostSelector
from .commands import GoalCommand, GoalCommandKind
from .engine import GoalEngineResult
from .events import GoalEvent, GoalEventKind
from .facility_rules import is_pre_service_replan_event, matches_committed_facility
from .graph import JourneyGoalNode
from .state import AgentGoalState, FacilityCommitment, FacilityInteractionState


CompleteFacilityGoal = Callable[[AgentGoalState, GoalEvent], GoalEngineResult]


class FacilityGoalReducer:
    """Pure reducer for the reusable decide -> queue -> service lifecycle."""

    def __init__(self, selector: GoalFacilitySelector | None = None) -> None:
        self.selector = selector or MinimumPerceivedCostSelector()

    def handle(
        self,
        state: AgentGoalState,
        node: JourneyGoalNode,
        event: GoalEvent,
        *,
        complete: CompleteFacilityGoal,
    ) -> GoalEngineResult:
        interaction = state.interaction_state
        if interaction == FacilityInteractionState.APPROACH_DECISION_REGION.value:
            return self._enter_decision_region(state, node, event)
        if interaction in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.WAITING_CAPACITY.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            return self._select_facility(state, node, event)
        if (
            event.kind == GoalEventKind.FACILITY_SELECTED.value
            and state.commitment is not None
            and event.facility_id == state.commitment.facility_id
        ):
            return GoalEngineResult(state=state)
        if is_pre_service_replan_event(state, event):
            return self._request_replan(state, event)
        if interaction == FacilityInteractionState.APPROACH_QUEUE.value:
            return self._capture_queue(state, event)
        if interaction == FacilityInteractionState.CAPTURE_QUEUE.value:
            return self._join_queue(state, event)
        if interaction == FacilityInteractionState.QUEUEING.value:
            return self._handle_queueing(state, node, event)
        if interaction == FacilityInteractionState.IN_SERVICE.value and matches_committed_facility(
            event, state, GoalEventKind.SERVICE_COMPLETED
        ):
            return complete(state, event)
        return GoalEngineResult(state=state, handled=False)

    def _handle_queueing(
        self,
        state: AgentGoalState,
        node: JourneyGoalNode,
        event: GoalEvent,
    ) -> GoalEngineResult:
        if event.kind == GoalEventKind.TRAIN_FULL.value:
            return GoalEngineResult(
                state=state,
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.WAIT_FOR_EVENT.value,
                        goal_node_id=node.node_id,
                        stage=node.facility_stage,
                        event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
                        reason=event.reason or GoalEventKind.TRAIN_FULL.value,
                    ),
                ),
            )
        if event.kind == GoalEventKind.TRAIN_AVAILABLE.value:
            return GoalEngineResult(
                state=state,
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.WAIT_FOR_SERVICE.value,
                        goal_node_id=node.node_id,
                        stage=node.facility_stage,
                        facility_id=state.queued_facility_id,
                    ),
                ),
            )
        return self._start_service(state, event)

    def _enter_decision_region(
        self,
        state: AgentGoalState,
        node: JourneyGoalNode,
        event: GoalEvent,
    ) -> GoalEngineResult:
        if event.kind != GoalEventKind.ENTERED_REGION.value:
            return GoalEngineResult(state=state, handled=False)
        if event.region_id != node.decision_region_id:
            return GoalEngineResult(state=state, handled=False)
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.EVALUATE_CANDIDATES.value,
            ),
            commands=(
                GoalCommand(
                    kind=GoalCommandKind.OBSERVE_CANDIDATES.value,
                    goal_node_id=node.node_id,
                    stage=node.facility_stage,
                    target_region_id=node.decision_region_id,
                ),
            ),
        )

    def _select_facility(
        self,
        state: AgentGoalState,
        node: JourneyGoalNode,
        event: GoalEvent,
    ) -> GoalEngineResult:
        if event.kind != GoalEventKind.CANDIDATES_UPDATED.value or event.observation is None:
            return GoalEngineResult(state=state, handled=False)
        selection = self.selector.choose(str(node.facility_stage), event.observation)
        if selection is None:
            if state.commitment is not None:
                return self._retain_current_facility(
                    state,
                    reason="hysteresis_retain:no_eligible_alternative",
                )
            if (
                event.observation.replan_reason == "decision_context_invalidated"
                and node.decision_region_id is not None
            ):
                return GoalEngineResult(
                    state=replace(
                        state,
                        interaction_state=(
                            FacilityInteractionState.APPROACH_DECISION_REGION.value
                        ),
                        commitment=None,
                        queued_facility_id=None,
                        replan_origin_interaction_state=None,
                        replan_reason=None,
                        replan_requested_at_seconds=None,
                    ),
                    commands=(
                        GoalCommand(
                            kind=GoalCommandKind.WALK_TO_REGION.value,
                            goal_node_id=node.node_id,
                            stage=node.facility_stage,
                            target_region_id=node.decision_region_id,
                            reason="decision_context_invalidated",
                        ),
                    ),
                )
            return GoalEngineResult(
                state=replace(
                    state,
                    interaction_state=FacilityInteractionState.WAITING_CAPACITY.value,
                    commitment=None,
                    queued_facility_id=None,
                    replan_origin_interaction_state=None,
                    replan_reason=None,
                    replan_requested_at_seconds=None,
                ),
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.WAIT_FOR_EVENT.value,
                        goal_node_id=node.node_id,
                        stage=node.facility_stage,
                        reason="no_eligible_facility",
                    ),
                ),
            )
        current_facility_id = (
            None if state.commitment is None else state.commitment.facility_id
        )
        if current_facility_id is not None and selection.facility_id == current_facility_id:
            return self._retain_current_facility(
                state,
                reason=selection.reason,
                selection=selection,
            )

        commitment = FacilityCommitment(
            facility_id=selection.facility_id,
            committed_at_seconds=event.time_seconds,
            reason=selection.reason,
            generalized_cost_seconds=selection.score,
            reconsider_after_seconds=selection.reconsider_after_seconds,
        )
        switch = current_facility_id is not None
        commands: list[GoalCommand] = []
        if switch:
            commands.append(
                GoalCommand(
                    kind=GoalCommandKind.REPLAN_STAGE.value,
                    goal_node_id=node.node_id,
                    stage=node.facility_stage,
                    facility_id=current_facility_id,
                    reason=state.replan_reason or "beneficial_alternative",
                    replan_cleanup_only=True,
                )
            )
        commands.extend(
            (
                self._selection_command(node, selection, action="switch" if switch else "select"),
                GoalCommand(
                    kind=GoalCommandKind.WALK_TO_QUEUE.value,
                    goal_node_id=node.node_id,
                    stage=node.facility_stage,
                    facility_id=selection.facility_id,
                ),
            )
        )
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.APPROACH_QUEUE.value,
                commitment=commitment,
                queued_facility_id=None,
                replan_origin_interaction_state=None,
                replan_reason=None,
                replan_requested_at_seconds=None,
                retry_count=state.retry_count + (1 if switch else 0),
            ),
            commands=tuple(commands),
        )

    def _retain_current_facility(
        self,
        state: AgentGoalState,
        *,
        reason: str,
        selection=None,
    ) -> GoalEngineResult:
        assert state.commitment is not None
        origin = state.replan_origin_interaction_state or FacilityInteractionState.APPROACH_QUEUE.value
        commitment = state.commitment
        if selection is not None:
            commitment = replace(
                commitment,
                generalized_cost_seconds=selection.score,
            )
            evidence = selection.as_dict()
        else:
            evidence = {
                "facility_id": commitment.facility_id,
                "score": commitment.generalized_cost_seconds,
                "reason": reason,
                "action": "retain",
                "candidate_costs": [],
            }
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=origin,
                commitment=commitment,
                replan_origin_interaction_state=None,
                replan_reason=None,
                replan_requested_at_seconds=None,
            ),
            commands=(
                GoalCommand(
                    kind=GoalCommandKind.SELECT_FACILITY.value,
                    goal_node_id=state.current_node_id,
                    stage=state.current_stage,
                    facility_id=commitment.facility_id,
                    reason=reason,
                    selection_action="retain",
                    decision_evidence=evidence,
                ),
            ),
        )

    @staticmethod
    def _selection_command(node: JourneyGoalNode, selection, *, action: str) -> GoalCommand:
        evidence = selection.as_dict()
        evidence["action"] = action
        return GoalCommand(
            kind=GoalCommandKind.SELECT_FACILITY.value,
            goal_node_id=node.node_id,
            stage=node.facility_stage,
            facility_id=selection.facility_id,
            reason=selection.reason,
            selection_action=action,
            decision_evidence=evidence,
        )

    def _capture_queue(self, state: AgentGoalState, event: GoalEvent) -> GoalEngineResult:
        if not matches_committed_facility(
            event,
            state,
            GoalEventKind.REACHED_QUEUE_CAPTURE,
        ):
            return GoalEngineResult(state=state, handled=False)
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.CAPTURE_QUEUE.value,
            ),
            commands=(
                GoalCommand(
                    kind=GoalCommandKind.JOIN_QUEUE.value,
                    goal_node_id=state.current_node_id,
                    stage=state.current_stage,
                    facility_id=event.facility_id,
                ),
            ),
        )

    def _join_queue(self, state: AgentGoalState, event: GoalEvent) -> GoalEngineResult:
        if not matches_committed_facility(event, state, GoalEventKind.QUEUE_JOINED):
            return GoalEngineResult(state=state, handled=False)
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.QUEUEING.value,
                queued_facility_id=event.facility_id,
            ),
            commands=(
                GoalCommand(
                    kind=GoalCommandKind.WAIT_FOR_SERVICE.value,
                    goal_node_id=state.current_node_id,
                    stage=state.current_stage,
                    facility_id=event.facility_id,
                ),
            ),
        )

    def _start_service(self, state: AgentGoalState, event: GoalEvent) -> GoalEngineResult:
        if not matches_committed_facility(event, state, GoalEventKind.SERVICE_STARTED):
            return GoalEngineResult(state=state, handled=False)
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.IN_SERVICE.value,
            )
        )

    def _request_replan(self, state: AgentGoalState, event: GoalEvent) -> GoalEngineResult:
        committed_facility_id = (
            event.facility_id
            or (state.commitment.facility_id if state.commitment is not None else None)
        )
        if event.kind == GoalEventKind.PROGRESS_STALLED.value:
            return GoalEngineResult(
                state=replace(
                    state,
                    interaction_state=FacilityInteractionState.REPLAN_PENDING.value,
                    replan_origin_interaction_state=state.interaction_state,
                    replan_reason=event.reason or event.kind,
                    replan_requested_at_seconds=event.time_seconds,
                ),
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.OBSERVE_CANDIDATES.value,
                        goal_node_id=state.current_node_id,
                        stage=state.current_stage,
                        facility_id=committed_facility_id,
                        reason=event.reason or event.kind,
                    ),
                ),
            )

        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=FacilityInteractionState.REPLAN_PENDING.value,
                commitment=None,
                queued_facility_id=None,
                retry_count=state.retry_count + 1,
                replan_origin_interaction_state=state.interaction_state,
                replan_reason=event.reason or event.kind,
                replan_requested_at_seconds=event.time_seconds,
            ),
            commands=(
                GoalCommand(
                    kind=GoalCommandKind.REPLAN_STAGE.value,
                    goal_node_id=state.current_node_id,
                    stage=state.current_stage,
                    facility_id=committed_facility_id,
                    reason=event.reason or event.kind,
                ),
            ),
        )
