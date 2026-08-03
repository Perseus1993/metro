from __future__ import annotations

from ..goals.events import GoalEventKind
from ..goals.graph import GoalNodeKind, JourneyGoalNode, JourneyGraph, JourneyTransition
from ..passengers import FacilityStage


def journey_graph_for_facility_chain(
    *,
    graph_id: str,
    facility_chain: tuple[str, ...],
    terminal_region_id: str | None = None,
) -> JourneyGraph:
    if not facility_chain:
        terminal = () if terminal_region_id is None else (_terminal_region(terminal_region_id),)
        return _facility_path_graph(graph_id=graph_id, steps=terminal)
    stage_totals = {stage: facility_chain.count(stage) for stage in set(facility_chain)}
    stage_indexes: dict[str, int] = {}
    steps: list[JourneyGoalNode] = []
    previous_stage: str | None = None
    for stage in facility_chain:
        stage_indexes[stage] = stage_indexes.get(stage, 0) + 1
        index = stage_indexes[stage]
        total = stage_totals[stage]
        intermediate = _intermediate_region(previous_stage, stage, index)
        if intermediate is not None:
            steps.append(_region(*intermediate))
        if stage == FacilityStage.BOARDING_DOOR.value:
            steps.append(
                JourneyGoalNode(
                    node_id=_numbered("wait_for_train", index, total),
                    kind=GoalNodeKind.WAIT_FOR_EVENT.value,
                    label="wait for train availability",
                    wait_event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
                )
            )
        decision_node_id, decision_region_id = _decision_region(stage, index, total)
        steps.append(_region(decision_node_id, decision_region_id))
        facility_node_id = _numbered(_facility_node_id(stage), index, total)
        steps.append(_facility(facility_node_id, stage, decision_region_id))
        previous_stage = stage
    if terminal_region_id is not None:
        steps.append(_terminal_region(terminal_region_id))
    return _facility_path_graph(graph_id=graph_id, steps=tuple(steps))


def station_exit_journey_graph(*, graph_id: str = "station_exit") -> JourneyGraph:
    return _facility_path_graph(
        graph_id=graph_id,
        steps=(
            _region("approach_vertical_decision", "vertical_decision"),
            _facility(
                "use_vertical_transfer",
                FacilityStage.VERTICAL_TRANSFER.value,
                "vertical_decision",
            ),
            _region("enter_exit_hall", "exit_hall"),
            _region("approach_exit_gate_decision", "exit_gate_decision"),
            _facility(
                "use_exit_gate",
                FacilityStage.EXIT_GATE.value,
                "exit_gate_decision",
            ),
            _terminal_region(
                "safe_zone" if graph_id == "station_evacuation" else "station_exit"
            ),
        ),
    )


def station_transfer_journey_graph() -> JourneyGraph:
    return _facility_path_graph(
        graph_id="station_transfer",
        steps=(
            _region("approach_vertical_decision", "vertical_decision"),
            _facility(
                "use_vertical_transfer",
                FacilityStage.VERTICAL_TRANSFER.value,
                "vertical_decision",
            ),
            _region("enter_platform_landing", "platform_landing"),
            JourneyGoalNode(
                node_id="wait_for_train",
                kind=GoalNodeKind.WAIT_FOR_EVENT.value,
                label="wait for target train",
                wait_event_kind=GoalEventKind.TRAIN_AVAILABLE.value,
            ),
            _region("approach_boarding_decision", "boarding_decision"),
            _facility(
                "use_boarding_door",
                FacilityStage.BOARDING_DOOR.value,
                "boarding_decision",
            ),
        ),
    )


def _terminal_region(region_id: str) -> JourneyGoalNode:
    return _region(f"reach_{region_id}", region_id)


def _region(node_id: str, region_id: str) -> JourneyGoalNode:
    return JourneyGoalNode(
        node_id=node_id,
        kind=GoalNodeKind.ENTER_REGION.value,
        label=node_id.replace("_", " "),
        region_id=region_id,
    )


def _facility(
    node_id: str,
    stage: str,
    decision_region_id: str,
) -> JourneyGoalNode:
    return JourneyGoalNode(
        node_id=node_id,
        kind=GoalNodeKind.USE_FACILITY_STAGE.value,
        label=node_id.replace("_", " "),
        facility_stage=stage,
        decision_region_id=decision_region_id,
    )


def _facility_path_graph(
    *,
    graph_id: str,
    steps: tuple[JourneyGoalNode, ...],
) -> JourneyGraph:
    complete = JourneyGoalNode(
        node_id="complete",
        kind=GoalNodeKind.COMPLETE.value,
        label=f"{graph_id} complete",
    )
    nodes = (*steps, complete)
    return JourneyGraph(
        graph_id=graph_id,
        entry_node_id=nodes[0].node_id,
        nodes=nodes,
        transitions=tuple(
            JourneyTransition(
                transition_id=f"{source.node_id}_completed",
                source_node_id=source.node_id,
                target_node_id=target.node_id,
                event_kind=(
                    str(source.wait_event_kind)
                    if source.kind == GoalNodeKind.WAIT_FOR_EVENT.value
                    else GoalEventKind.GOAL_COMPLETED.value
                ),
            )
            for source, target in zip(nodes, nodes[1:])
        )
        + tuple(
            JourneyTransition(
                transition_id=f"{node.node_id}_timeout_fallback",
                source_node_id=node.node_id,
                target_node_id=node.node_id,
                event_kind=GoalEventKind.WAIT_TIMEOUT.value,
            )
            for node in nodes
            if node.kind == GoalNodeKind.WAIT_FOR_EVENT.value
        ),
    )


def _decision_region(stage: str, index: int, total: int) -> tuple[str, str]:
    names = {
        FacilityStage.ENTRY_GATE.value: ("approach_entry_gate_decision", "entry_gate_decision"),
        FacilityStage.VERTICAL_TRANSFER.value: (
            "approach_vertical_decision",
            "vertical_decision",
        ),
        FacilityStage.BOARDING_DOOR.value: (
            "approach_boarding_decision",
            "boarding_decision",
        ),
        FacilityStage.EXIT_GATE.value: (
            "approach_exit_gate_decision",
            "exit_gate_decision",
        ),
    }
    try:
        node_id, region_id = names[stage]
    except KeyError as exc:
        raise ValueError(f"unsupported facility stage in journey chain {stage!r}") from exc
    return _numbered(node_id, index, total), _numbered(region_id, index, total)


def _facility_node_id(stage: str) -> str:
    return {
        FacilityStage.ENTRY_GATE.value: "use_entry_gate",
        FacilityStage.VERTICAL_TRANSFER.value: "use_vertical_transfer",
        FacilityStage.BOARDING_DOOR.value: "use_boarding_door",
        FacilityStage.EXIT_GATE.value: "use_exit_gate",
    }[stage]


def _intermediate_region(
    previous_stage: str | None,
    stage: str,
    index: int,
) -> tuple[str, str] | None:
    if previous_stage == FacilityStage.ENTRY_GATE.value:
        return "enter_paid_hall", "paid_hall"
    if previous_stage == FacilityStage.VERTICAL_TRANSFER.value:
        if stage == FacilityStage.VERTICAL_TRANSFER.value:
            suffix = max(1, index - 1)
            return f"enter_vertical_landing_{suffix}", f"vertical_landing_{suffix}"
        if stage == FacilityStage.BOARDING_DOOR.value:
            return "enter_platform_landing", "platform_landing"
        if stage == FacilityStage.EXIT_GATE.value:
            return "enter_exit_hall", "exit_hall"
    return None


def _numbered(value: str, index: int, total: int) -> str:
    return value if total <= 1 else f"{value}_{index}"
