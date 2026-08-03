from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..goals.graph import JourneyGoalNode, JourneyGraph, JourneyTransition


def journey_graph_to_dict(graph: JourneyGraph) -> dict[str, Any]:
    return {
        "id": graph.graph_id,
        "version": graph.version,
        "entry_node_id": graph.entry_node_id,
        "nodes": [_node_to_dict(node) for node in graph.nodes],
        "transitions": [_transition_to_dict(item) for item in graph.transitions],
    }


def journey_graph_from_mapping(payload: Mapping[str, Any]) -> JourneyGraph:
    return JourneyGraph(
        graph_id=str(payload["id"]),
        version=int(payload.get("version", 1)),
        entry_node_id=str(payload["entry_node_id"]),
        nodes=tuple(_node_from_mapping(item) for item in payload["nodes"]),
        transitions=tuple(
            _transition_from_mapping(item) for item in payload["transitions"]
        ),
    )


def _node_to_dict(node: JourneyGoalNode) -> dict[str, Any]:
    return {
        "id": node.node_id,
        "kind": node.kind,
        "label": node.label,
        "region_id": node.region_id,
        "facility_stage": node.facility_stage,
        "decision_region_id": node.decision_region_id,
        "wait_event_kind": node.wait_event_kind,
        "metadata": dict(node.metadata),
    }


def _node_from_mapping(payload: Mapping[str, Any]) -> JourneyGoalNode:
    metadata = payload.get("metadata", {})
    return JourneyGoalNode(
        node_id=str(payload["id"]),
        kind=str(payload["kind"]),
        label=str(payload.get("label", payload["id"])),
        region_id=_optional_text(payload.get("region_id")),
        facility_stage=_optional_text(payload.get("facility_stage")),
        decision_region_id=_optional_text(payload.get("decision_region_id")),
        wait_event_kind=_optional_text(payload.get("wait_event_kind")),
        metadata=tuple(
            sorted((str(key), str(value)) for key, value in dict(metadata).items())
        ),
    )


def _transition_to_dict(transition: JourneyTransition) -> dict[str, str | None]:
    return {
        "id": transition.transition_id,
        "source": transition.source_node_id,
        "target": transition.target_node_id,
        "event": transition.event_kind,
        "guard": transition.guard_id,
    }


def _transition_from_mapping(payload: Mapping[str, Any]) -> JourneyTransition:
    return JourneyTransition(
        transition_id=str(payload["id"]),
        source_node_id=str(payload["source"]),
        target_node_id=str(payload["target"]),
        event_kind=str(payload["event"]),
        guard_id=_optional_text(payload.get("guard")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
