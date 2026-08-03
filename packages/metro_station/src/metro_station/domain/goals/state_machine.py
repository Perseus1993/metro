from __future__ import annotations

from dataclasses import replace

from .choice import GoalFacilitySelector
from .commands import GoalCommand, GoalCommandKind
from .engine import GoalEngineResult
from .events import GoalEvent, GoalEventKind
from .facility_reducer import FacilityGoalReducer
from .graph import GoalNodeKind, JourneyGoalNode, JourneyGraph, JourneyTransition
from .guards import GoalGuardRegistry
from .state import AgentGoalState, FacilityInteractionState


class EventDrivenGoalStateMachine:
    """Pure journey executor; it emits commands but never changes the outside world."""

    def __init__(
        self,
        selector: GoalFacilitySelector | None = None,
        *,
        guards: GoalGuardRegistry | None = None,
    ) -> None:
        self.facility_reducer = FacilityGoalReducer(selector)
        self.guards = dict(guards or {})

    def start(
        self,
        graph: JourneyGraph,
        *,
        at_time_seconds: float = 0.0,
    ) -> GoalEngineResult:
        if at_time_seconds < 0:
            raise ValueError("goal state machine start time cannot be negative")
        state = AgentGoalState(
            journey_graph_id=graph.graph_id,
            journey_graph_version=graph.version,
            current_node_id=graph.entry_node_id,
            last_event_time_seconds=at_time_seconds,
        )
        return self._activate_node(graph.node(graph.entry_node_id), state, None)

    def handle(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> GoalEngineResult:
        self._validate_state_graph(graph, state)
        if event.event_id is not None and event.event_id in state.processed_event_ids:
            return GoalEngineResult(state=state, handled=False)
        if event.time_seconds < state.last_event_time_seconds:
            raise ValueError("goal event time cannot move backwards")
        result = self._dispatch(graph, state, event)
        if not result.handled:
            return result
        processed = result.state.processed_event_ids
        if event.event_id is not None:
            processed = (*processed, event.event_id)[-256:]
        return replace(
            result,
            state=replace(
                result.state,
                last_event_time_seconds=event.time_seconds,
                processed_event_ids=processed,
            ),
        )

    def _dispatch(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> GoalEngineResult:
        node = graph.node(state.current_node_id)
        if node.kind == GoalNodeKind.ENTER_REGION.value:
            return self._handle_region_goal(graph, state, node, event)
        if node.kind == GoalNodeKind.USE_FACILITY_STAGE.value:
            return self.facility_reducer.handle(
                state,
                node,
                event,
                complete=lambda current, trigger: self._advance(graph, current, trigger),
            )
        if node.kind == GoalNodeKind.WAIT_FOR_EVENT.value:
            if event.kind in {node.wait_event_kind, GoalEventKind.WAIT_TIMEOUT.value}:
                return self._advance(graph, state, event)
            if (
                node.wait_event_kind == GoalEventKind.TRAIN_AVAILABLE.value
                and event.kind == GoalEventKind.TRAIN_FULL.value
            ):
                # A full train is a meaningful observation, not a transition:
                # retain the wait node while advancing event time/idempotency
                # evidence so a later train_available fact can complete it.
                return GoalEngineResult(state=state)
            return GoalEngineResult(state=state, handled=False)
        if (
            node.kind == GoalNodeKind.COMPLETE.value
            and event.kind == GoalEventKind.TERMINAL_REACHED.value
        ):
            return GoalEngineResult(state=state)
        return GoalEngineResult(state=state, handled=False)

    def _handle_region_goal(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        node: JourneyGoalNode,
        event: GoalEvent,
    ) -> GoalEngineResult:
        if event.kind != GoalEventKind.ENTERED_REGION.value:
            return GoalEngineResult(state=state, handled=False)
        if event.region_id != node.region_id:
            return GoalEngineResult(state=state, handled=False)
        return self._advance(graph, state, event)

    def _advance(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> GoalEngineResult:
        transitions = self._eligible_transitions(graph, state, event)
        if len(transitions) != 1:
            raise ValueError(
                f"goal {state.current_node_id!r} requires exactly one eligible transition "
                f"for event {event.kind!r}; got {len(transitions)}"
            )
        next_node = graph.node(transitions[0].target_node_id)
        next_state = replace(
            state,
            current_node_id=next_node.node_id,
            interaction_state=None,
            current_stage=None,
            commitment=None,
            queued_facility_id=None,
            replan_origin_interaction_state=None,
            replan_reason=None,
            replan_requested_at_seconds=None,
            transition_count=state.transition_count + 1,
        )
        return self._activate_node(next_node, next_state, event)

    def _eligible_transitions(
        self,
        graph: JourneyGraph,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> tuple[JourneyTransition, ...]:
        outgoing = graph.outgoing(state.current_node_id)
        exact = tuple(item for item in outgoing if item.event_kind == event.kind)
        eligible = tuple(item for item in exact if self._guard_allows(item.guard_id, state, event))
        if eligible:
            return eligible
        fallback = tuple(
            item
            for item in outgoing
            if item.event_kind == GoalEventKind.GOAL_COMPLETED.value
        )
        return tuple(
            item for item in fallback if self._guard_allows(item.guard_id, state, event)
        )

    def _guard_allows(
        self,
        guard_id: str | None,
        state: AgentGoalState,
        event: GoalEvent,
    ) -> bool:
        if guard_id is None:
            return True
        guard = self.guards.get(guard_id)
        if guard is None:
            raise ValueError(f"unknown goal transition guard {guard_id!r}")
        return bool(guard(state, event))

    def _activate_node(
        self,
        node: JourneyGoalNode,
        state: AgentGoalState,
        trigger: GoalEvent | None,
    ) -> GoalEngineResult:
        if node.kind == GoalNodeKind.ENTER_REGION.value:
            return GoalEngineResult(
                state=state,
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.WALK_TO_REGION.value,
                        goal_node_id=node.node_id,
                        target_region_id=node.region_id,
                    ),
                ),
            )
        if node.kind == GoalNodeKind.USE_FACILITY_STAGE.value:
            return self._activate_facility_node(node, state, trigger)
        if node.kind == GoalNodeKind.WAIT_FOR_EVENT.value:
            return GoalEngineResult(
                state=state,
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.WAIT_FOR_EVENT.value,
                        goal_node_id=node.node_id,
                        event_kind=node.wait_event_kind,
                    ),
                ),
            )
        if node.kind == GoalNodeKind.COMPLETE.value:
            return GoalEngineResult(
                state=state,
                commands=(
                    GoalCommand(
                        kind=GoalCommandKind.COMPLETE_JOURNEY.value,
                        goal_node_id=node.node_id,
                    ),
                ),
            )
        return GoalEngineResult(state=state)

    def _activate_facility_node(
        self,
        node: JourneyGoalNode,
        state: AgentGoalState,
        trigger: GoalEvent | None,
    ) -> GoalEngineResult:
        already_inside = (
            trigger is not None
            and trigger.kind == GoalEventKind.ENTERED_REGION.value
            and trigger.region_id == node.decision_region_id
        )
        interaction = (
            FacilityInteractionState.EVALUATE_CANDIDATES
            if already_inside
            else FacilityInteractionState.APPROACH_DECISION_REGION
        )
        command = (
            GoalCommand(
                kind=GoalCommandKind.OBSERVE_CANDIDATES.value,
                goal_node_id=node.node_id,
                stage=node.facility_stage,
                target_region_id=node.decision_region_id,
            )
            if already_inside
            else GoalCommand(
                kind=GoalCommandKind.WALK_TO_REGION.value,
                goal_node_id=node.node_id,
                target_region_id=node.decision_region_id,
            )
        )
        return GoalEngineResult(
            state=replace(
                state,
                interaction_state=interaction.value,
                current_stage=node.facility_stage,
            ),
            commands=(command,),
        )

    def _validate_state_graph(self, graph: JourneyGraph, state: AgentGoalState) -> None:
        if state.journey_graph_id != graph.graph_id:
            raise ValueError("agent goal state belongs to a different journey graph")
        if state.journey_graph_version != graph.version:
            raise ValueError("agent goal state journey graph version mismatch")
