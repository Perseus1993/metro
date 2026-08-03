from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GoalNodeKind(StrEnum):
    ENTER_REGION = "enter_region"
    USE_FACILITY_STAGE = "use_facility_stage"
    WAIT_FOR_EVENT = "wait_for_event"
    COMPLETE = "complete"


@dataclass(frozen=True)
class JourneyGoalNode:
    node_id: str
    kind: str
    label: str
    region_id: str | None = None
    facility_stage: str | None = None
    decision_region_id: str | None = None
    wait_event_kind: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("journey goal node_id cannot be blank")
        if not self.label.strip():
            raise ValueError(f"journey goal {self.node_id!r} label cannot be blank")
        try:
            kind = GoalNodeKind(self.kind)
        except ValueError as exc:
            raise ValueError(f"unsupported journey goal kind {self.kind!r}") from exc
        if kind == GoalNodeKind.ENTER_REGION and not self.region_id:
            raise ValueError(f"enter-region goal {self.node_id!r} requires region_id")
        if kind == GoalNodeKind.USE_FACILITY_STAGE:
            if not self.facility_stage:
                raise ValueError(f"facility goal {self.node_id!r} requires facility_stage")
            if not self.decision_region_id:
                raise ValueError(f"facility goal {self.node_id!r} requires decision_region_id")
        if kind == GoalNodeKind.WAIT_FOR_EVENT and not self.wait_event_kind:
            raise ValueError(f"wait goal {self.node_id!r} requires wait_event_kind")


@dataclass(frozen=True)
class JourneyTransition:
    transition_id: str
    source_node_id: str
    target_node_id: str
    event_kind: str
    guard_id: str | None = None

    def __post_init__(self) -> None:
        required = {
            "transition_id": self.transition_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "event_kind": self.event_kind,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise ValueError(f"journey transition {field_name} cannot be blank")


@dataclass(frozen=True)
class JourneyGraph:
    graph_id: str
    entry_node_id: str
    nodes: tuple[JourneyGoalNode, ...]
    transitions: tuple[JourneyTransition, ...]
    version: int = 1
    _nodes_by_id: dict[str, JourneyGoalNode] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.graph_id.strip():
            raise ValueError("journey graph_id cannot be blank")
        if self.version <= 0:
            raise ValueError("journey graph version must be positive")
        nodes_by_id = _unique_nodes(self.nodes)
        object.__setattr__(self, "_nodes_by_id", nodes_by_id)
        self._validate(nodes_by_id)

    def node(self, node_id: str) -> JourneyGoalNode:
        try:
            return self._nodes_by_id[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown journey goal node {node_id!r}") from exc

    def outgoing(
        self,
        node_id: str,
        *,
        event_kind: str | None = None,
    ) -> tuple[JourneyTransition, ...]:
        self.node(node_id)
        return tuple(
            transition
            for transition in self.transitions
            if transition.source_node_id == node_id
            and (event_kind is None or transition.event_kind == event_kind)
        )

    def _validate(self, nodes_by_id: dict[str, JourneyGoalNode]) -> None:
        if self.entry_node_id not in nodes_by_id:
            raise ValueError(f"journey entry node {self.entry_node_id!r} does not exist")
        if not any(node.kind == GoalNodeKind.COMPLETE.value for node in self.nodes):
            raise ValueError("journey graph requires at least one complete goal")

        transition_ids: set[str] = set()
        for transition in self.transitions:
            if transition.transition_id in transition_ids:
                raise ValueError(f"duplicate journey transition {transition.transition_id!r}")
            transition_ids.add(transition.transition_id)
            if transition.source_node_id not in nodes_by_id:
                raise ValueError(
                    f"journey transition source {transition.source_node_id!r} does not exist"
                )
            if transition.target_node_id not in nodes_by_id:
                raise ValueError(
                    f"journey transition target {transition.target_node_id!r} does not exist"
                )
            source = nodes_by_id[transition.source_node_id]
            if source.kind == GoalNodeKind.COMPLETE.value:
                raise ValueError(f"complete goal {source.node_id!r} cannot have outgoing transitions")

        reachable = {self.entry_node_id}
        frontier = [self.entry_node_id]
        while frontier:
            source_id = frontier.pop()
            for transition in self.outgoing(source_id):
                if transition.target_node_id in reachable:
                    continue
                reachable.add(transition.target_node_id)
                frontier.append(transition.target_node_id)
        unreachable = sorted(set(nodes_by_id) - reachable)
        if unreachable:
            raise ValueError(f"unreachable journey goals: {', '.join(unreachable)}")


def _unique_nodes(nodes: tuple[JourneyGoalNode, ...]) -> dict[str, JourneyGoalNode]:
    if not nodes:
        raise ValueError("journey graph requires at least one goal node")
    nodes_by_id: dict[str, JourneyGoalNode] = {}
    for node in nodes:
        if node.node_id in nodes_by_id:
            raise ValueError(f"duplicate journey goal node {node.node_id!r}")
        nodes_by_id[node.node_id] = node
    return nodes_by_id
