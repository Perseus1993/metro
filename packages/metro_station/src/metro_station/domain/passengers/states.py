from enum import StrEnum


class AgentIntent(StrEnum):
    ENTER_AND_BOARD = "enter_and_board"
    EXIT_STATION = "exit_station"
    EVACUATE_STATION = "evacuate_station"
    TRANSFER = "transfer"


class FacilityStage(StrEnum):
    ENTRY_GATE = "entry_gate"
    VERTICAL_TRANSFER = "vertical_transfer"
    BOARDING_DOOR = "boarding_door"
    EXIT_GATE = "exit_gate"


class RouteKey(StrEnum):
    CURRENT_POSITION = "current_position"
    ENTRY_GATE_DECISION = "entry_gate_decision"
    AFTER_GATE = "after_gate"
    AFTER_VERTICAL = "after_vertical"
    PLATFORM_TO_VERTICAL = "platform_to_vertical"
    AFTER_EXIT_VERTICAL = "after_exit_vertical"


class AgentState(StrEnum):
    ENTERING_STATION = "entering_station"
    QUEUEING_GATE = "queueing_gate"
    PASSING_GATE = "passing_gate"
    WALKING_TO_VERTICAL = "walking_to_vertical"
    QUEUEING_VERTICAL = "queueing_vertical"
    RIDING_VERTICAL = "riding_vertical"
    WALKING_TO_PLATFORM = "walking_to_platform"
    WAITING_PLATFORM = "waiting_platform"
    QUEUEING_DOOR = "queueing_door"
    BOARDING_TRAIN = "boarding_train"
    WALKING_TO_EXIT_GATE = "walking_to_exit_gate"
    QUEUEING_EXIT_GATE = "queueing_exit_gate"
    PASSING_EXIT_GATE = "passing_exit_gate"
    WALKING_TO_TRANSFER = "walking_to_transfer"
    DEPARTED = "departed"


PASSIVE_STATES = {
    AgentState.QUEUEING_GATE.value,
    AgentState.QUEUEING_VERTICAL.value,
    AgentState.WAITING_PLATFORM.value,
    AgentState.QUEUEING_DOOR.value,
    AgentState.BOARDING_TRAIN.value,
    AgentState.QUEUEING_EXIT_GATE.value,
    AgentState.DEPARTED.value,
}


WALKING_STATES = {
    AgentState.ENTERING_STATION.value,
    AgentState.WALKING_TO_VERTICAL.value,
    AgentState.WALKING_TO_PLATFORM.value,
    AgentState.WALKING_TO_EXIT_GATE.value,
    AgentState.WALKING_TO_TRANSFER.value,
}


SERVICE_STATES = {
    AgentState.PASSING_GATE.value,
    AgentState.RIDING_VERTICAL.value,
    AgentState.BOARDING_TRAIN.value,
    AgentState.PASSING_EXIT_GATE.value,
}


CROWD_INTERACTION_STATES = {
    *WALKING_STATES,
    AgentState.QUEUEING_DOOR.value,
}
