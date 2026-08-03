from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metro_station.domain.passengers import (
    CROWD_INTERACTION_STATES,
    PASSIVE_STATES,
    SERVICE_STATES,
    WALKING_STATES,
    AgentIntent,
    AgentState,
    FacilityStage,
    RouteKey,
)


Point = tuple[float, float]

__all__ = [
    "CROWD_INTERACTION_STATES",
    "PASSIVE_STATES",
    "SERVICE_STATES",
    "WALKING_STATES",
    "AgentGoal",
    "AgentIntent",
    "AgentPlan",
    "AgentState",
    "FacilityStage",
    "RouteKey",
]


@dataclass(frozen=True)
class AgentGoal:
    kind: str
    label: str
    target: Point | None = None
    facility_id: str | None = None
    stage: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "target": self.target,
            "facility_id": self.facility_id,
            "stage": self.stage,
        }


@dataclass
class AgentPlan:
    """Temporary physical goal adapter; strategic decisions belong to Goal Graph."""

    intent: str
    initial_state: str = AgentState.ENTERING_STATION.value
    initial_route_key: str = RouteKey.ENTRY_GATE_DECISION.value
    initial_goal_label: str = "entry gate decision"
    current_goal: AgentGoal = AgentGoal(kind="idle", label="not_started")

    @classmethod
    def enter_and_board(cls) -> "AgentPlan":
        return cls(
            intent=AgentIntent.ENTER_AND_BOARD.value,
        )

    @classmethod
    def exit_station(
        cls,
        intent: str | AgentIntent = AgentIntent.EXIT_STATION,
    ) -> "AgentPlan":
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        return cls(
            intent=intent_value,
            initial_state=AgentState.WALKING_TO_VERTICAL.value,
            initial_route_key=RouteKey.PLATFORM_TO_VERTICAL.value,
            initial_goal_label="vertical transfer decision",
        )

    @classmethod
    def transfer(cls) -> "AgentPlan":
        return cls(
            intent=AgentIntent.TRANSFER.value,
            initial_state=AgentState.WALKING_TO_VERTICAL.value,
            initial_route_key=RouteKey.PLATFORM_TO_VERTICAL.value,
            initial_goal_label="transfer vertical decision",
        )

    @classmethod
    def for_intent(cls, intent: str | AgentIntent) -> "AgentPlan":
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        if intent_value in {
            AgentIntent.EXIT_STATION.value,
            AgentIntent.EVACUATE_STATION.value,
        }:
            return cls.exit_station(intent_value)
        if intent_value == AgentIntent.TRANSFER.value:
            return cls.transfer()
        return cls.enter_and_board()

    def set_goal(
        self,
        *,
        kind: str,
        label: str,
        target: Point | None = None,
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        self.current_goal = AgentGoal(
            kind=kind,
            label=label,
            target=target,
            facility_id=facility_id,
            stage=None
            if stage is None
            else stage.value
            if isinstance(stage, FacilityStage)
            else str(stage),
        )
