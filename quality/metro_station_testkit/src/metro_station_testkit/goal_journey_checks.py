"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.facilities.process import FacilityKind
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_journey_fixture import CONCOURSE_LEVEL, PLATFORM_LEVEL
from .goal_journey_micro_scene import GoalJourneyMicroScene
from .goal_journey_trace import GoalJourneyTraceStep


EXPECTED_SERVICE_KINDS = (
    FacilityKind.GATE.value,
    FacilityKind.STAIRS.value,
    FacilityKind.TRAIN_DOOR.value,
)


def journey_probe_checks(
    scenario_id: str,
    scene: GoalJourneyMicroScene,
    state: AgentGoalState,
    traces: list[GoalJourneyTraceStep],
    *,
    completed_at: float | None,
) -> dict[str, bool]:
    completed = state.current_node_id == "complete"
    if scenario_id == "train_full_after_full_journey":
        return {
            "not_completed": not completed,
            "gate_and_stairs_completed": _service_kinds(scene)
            == EXPECTED_SERVICE_KINDS[:2],
            "not_boarded": scene.boarded_persons == 0,
            "platform_level_reached": scene.subject.current_level_id == PLATFORM_LEVEL,
            "train_capacity_zero": scene.train.capacity_remaining == 0,
        }
    checks = _completed_checks(scene, completed)
    if scenario_id == "crowded_full_journey":
        checks.update(
            {
                "large_background_crowd": len(scene.crowd) >= 90,
                "three_stage_replans": _replanned_stage_count(traces) == 3,
                "three_stalls": sum(
                    trace.event_kind == "progress_stalled" for trace in traces
                )
                >= 3,
            }
        )
        return checks
    if scenario_id == "gate_replan":
        checks.update(_reroute_checks(traces, "gate_1", "gate_2"))
    elif scenario_id == "stairs_replan":
        checks.update(_reroute_checks(traces, "stairs_1", "stairs_2"))
    elif scenario_id == "door_replan":
        checks.update(_reroute_checks(traces, "door_1", "door_2"))
    elif scenario_id == "delayed_train":
        checks["waited_in_door_queue"] = _queue_wait_seconds(traces) >= 9.5
    elif scenario_id == "no_stage_regression":
        checks.update(
            {
                "post_completion_observed": completed_at is not None
                and scene.current_time_seconds >= completed_at + 2.0,
                "no_level_regression": _no_level_regression(traces),
                "not_readded": scene.subject not in scene.passengers,
                "not_requeued": all(
                    scene.subject not in facility.queue for facility in scene.facilities
                ),
            }
        )
    return checks


def _completed_checks(scene: GoalJourneyMicroScene, completed: bool) -> dict[str, bool]:
    return {
        "completed": completed,
        "three_services_in_order": _service_kinds(scene) == EXPECTED_SERVICE_KINDS,
        "exactly_three_services": len(scene.facility_service_events) == 3,
        "boarded_once": scene.boarded_persons == 1,
        "passenger_departed": scene.subject.state == AgentState.DEPARTED.value,
        "final_platform_level": scene.subject.current_level_id == PLATFORM_LEVEL,
    }


def _service_kinds(scene: GoalJourneyMicroScene) -> tuple[str, ...]:
    return tuple(event.facility_kind for event in scene.facility_service_events)


def _reroute_checks(
    traces: list[GoalJourneyTraceStep],
    first: str,
    second: str,
) -> dict[str, bool]:
    facilities = [trace.committed_facility_id for trace in traces]
    return {
        f"selected_{first}": first in facilities,
        f"rerouted_{second}": second in facilities,
        "stall_emitted": any(trace.event_kind == "progress_stalled" for trace in traces),
    }


def _queue_wait_seconds(traces: list[GoalJourneyTraceStep]) -> float:
    joined = [trace.time_seconds for trace in traces if trace.event_kind == "queue_joined"]
    started = [trace.time_seconds for trace in traces if trace.event_kind == "service_started"]
    if not joined or not started:
        return 0.0
    return started[-1] - joined[-1]


def _no_level_regression(traces: list[GoalJourneyTraceStep]) -> bool:
    levels = [trace.level_id for trace in traces]
    try:
        platform_index = levels.index(PLATFORM_LEVEL)
    except ValueError:
        return False
    return CONCOURSE_LEVEL not in levels[platform_index:]


def _replanned_stage_count(traces: list[GoalJourneyTraceStep]) -> int:
    replanned = {
        trace.current_stage
        for trace in traces
        if trace.event_kind == "progress_stalled" and trace.current_stage is not None
    }
    return len(replanned)
