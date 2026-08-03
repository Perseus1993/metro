from __future__ import annotations

from ..goals.events import GoalEventKind
from ..goals.graph import GoalNodeKind, JourneyGoalNode, JourneyGraph, JourneyTransition
from ..passengers import FacilityStage


def entry_gate_journey_graph() -> JourneyGraph:
    """Minimal pure journey: entrance decision area -> entry gate -> paid hall."""

    return JourneyGraph(
        graph_id="entry_gate_vertical_slice",
        entry_node_id="approach_entry_gate_decision",
        nodes=(
            JourneyGoalNode(
                node_id="approach_entry_gate_decision",
                kind=GoalNodeKind.ENTER_REGION.value,
                label="approach entry gate decision region",
                region_id="entry_gate_decision",
            ),
            JourneyGoalNode(
                node_id="use_entry_gate",
                kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                label="choose and pass an entry gate",
                facility_stage=FacilityStage.ENTRY_GATE.value,
                decision_region_id="entry_gate_decision",
            ),
            JourneyGoalNode(
                node_id="enter_paid_hall",
                kind=GoalNodeKind.ENTER_REGION.value,
                label="enter paid hall",
                region_id="paid_hall",
            ),
            JourneyGoalNode(
                node_id="complete",
                kind=GoalNodeKind.COMPLETE.value,
                label="entry gate stage completed",
            ),
        ),
        transitions=(
            JourneyTransition(
                transition_id="decision_region_reached",
                source_node_id="approach_entry_gate_decision",
                target_node_id="use_entry_gate",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
            JourneyTransition(
                transition_id="entry_gate_completed",
                source_node_id="use_entry_gate",
                target_node_id="enter_paid_hall",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
            JourneyTransition(
                transition_id="paid_hall_reached",
                source_node_id="enter_paid_hall",
                target_node_id="complete",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
        ),
    )


def vertical_transfer_journey_graph() -> JourneyGraph:
    """Minimal pure journey: vertical lobby -> stairs -> destination landing."""

    return JourneyGraph(
        graph_id="vertical_transfer_slice",
        entry_node_id="approach_vertical_decision",
        nodes=(
            JourneyGoalNode(
                node_id="approach_vertical_decision",
                kind=GoalNodeKind.ENTER_REGION.value,
                label="approach vertical transfer decision region",
                region_id="vertical_decision",
            ),
            JourneyGoalNode(
                node_id="use_vertical_transfer",
                kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                label="choose and use a vertical transfer facility",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                decision_region_id="vertical_decision",
            ),
            JourneyGoalNode(
                node_id="enter_platform_landing",
                kind=GoalNodeKind.ENTER_REGION.value,
                label="enter destination landing",
                region_id="platform_landing",
            ),
            JourneyGoalNode(
                node_id="complete",
                kind=GoalNodeKind.COMPLETE.value,
                label="vertical transfer completed",
            ),
        ),
        transitions=(
            JourneyTransition(
                transition_id="vertical_decision_reached",
                source_node_id="approach_vertical_decision",
                target_node_id="use_vertical_transfer",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
            JourneyTransition(
                transition_id="vertical_service_completed",
                source_node_id="use_vertical_transfer",
                target_node_id="enter_platform_landing",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
            JourneyTransition(
                transition_id="platform_landing_reached",
                source_node_id="enter_platform_landing",
                target_node_id="complete",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
        ),
    )


def boarding_journey_graph() -> JourneyGraph:
    """Minimal pure journey: platform decision area -> train door -> boarded."""

    return JourneyGraph(
        graph_id="platform_boarding_slice",
        entry_node_id="approach_boarding_decision",
        nodes=(
            JourneyGoalNode(
                node_id="approach_boarding_decision",
                kind=GoalNodeKind.ENTER_REGION.value,
                label="approach boarding door decision region",
                region_id="boarding_decision",
            ),
            JourneyGoalNode(
                node_id="use_boarding_door",
                kind=GoalNodeKind.USE_FACILITY_STAGE.value,
                label="choose a train door and board",
                facility_stage=FacilityStage.BOARDING_DOOR.value,
                decision_region_id="boarding_decision",
            ),
            JourneyGoalNode(
                node_id="complete",
                kind=GoalNodeKind.COMPLETE.value,
                label="passenger boarded train",
            ),
        ),
        transitions=(
            JourneyTransition(
                transition_id="boarding_decision_reached",
                source_node_id="approach_boarding_decision",
                target_node_id="use_boarding_door",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
            JourneyTransition(
                transition_id="boarding_completed",
                source_node_id="use_boarding_door",
                target_node_id="complete",
                event_kind=GoalEventKind.GOAL_COMPLETED.value,
            ),
        ),
    )


def station_entry_to_boarding_journey_graph() -> JourneyGraph:
    """End-to-end journey from station entrance through boarding."""

    region_nodes = (
        ("approach_entry_gate_decision", "entry_gate_decision"),
        ("enter_paid_hall", "paid_hall"),
        ("approach_vertical_decision", "vertical_decision"),
        ("enter_platform_landing", "platform_landing"),
        ("approach_boarding_decision", "boarding_decision"),
    )
    nodes = tuple(
        JourneyGoalNode(
            node_id=node_id,
            kind=GoalNodeKind.ENTER_REGION.value,
            label=node_id.replace("_", " "),
            region_id=region_id,
        )
        for node_id, region_id in region_nodes
    ) + (
        JourneyGoalNode(
            node_id="use_entry_gate",
            kind=GoalNodeKind.USE_FACILITY_STAGE.value,
            label="choose and pass an entry gate",
            facility_stage=FacilityStage.ENTRY_GATE.value,
            decision_region_id="entry_gate_decision",
        ),
        JourneyGoalNode(
            node_id="use_vertical_transfer",
            kind=GoalNodeKind.USE_FACILITY_STAGE.value,
            label="choose and use a vertical transfer",
            facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
            decision_region_id="vertical_decision",
        ),
        JourneyGoalNode(
            node_id="use_boarding_door",
            kind=GoalNodeKind.USE_FACILITY_STAGE.value,
            label="choose a train door and board",
            facility_stage=FacilityStage.BOARDING_DOOR.value,
            decision_region_id="boarding_decision",
        ),
        JourneyGoalNode(
            node_id="complete",
            kind=GoalNodeKind.COMPLETE.value,
            label="station entry and boarding completed",
        ),
    )
    path = (
        "approach_entry_gate_decision",
        "use_entry_gate",
        "enter_paid_hall",
        "approach_vertical_decision",
        "use_vertical_transfer",
        "enter_platform_landing",
        "approach_boarding_decision",
        "use_boarding_door",
        "complete",
    )
    nodes_by_id = {node.node_id: node for node in nodes}
    transitions = tuple(
        JourneyTransition(
            transition_id=f"{source}_completed",
            source_node_id=source,
            target_node_id=target,
            event_kind=(
                str(nodes_by_id[source].wait_event_kind)
                if nodes_by_id[source].kind == GoalNodeKind.WAIT_FOR_EVENT.value
                else GoalEventKind.GOAL_COMPLETED.value
            ),
        )
        for source, target in zip(path, path[1:])
    )
    return JourneyGraph(
        graph_id="station_entry_to_boarding",
        entry_node_id=path[0],
        nodes=nodes,
        transitions=transitions,
    )
