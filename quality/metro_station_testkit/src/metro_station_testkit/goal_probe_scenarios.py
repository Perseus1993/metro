"""Goal Graph probe migrated from the planning production namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from .goal_probe import GoalProbeResult
from .goal_probe_fixtures import (
    complete_gate,
    enter_decision,
    enter_paid_hall,
    gate,
    goal_probe_recorder,
    update_candidates,
)
from metro_station.adapters.simulation.planning.goal_state import FacilityInteractionState


def run_goal_probe_scenarios() -> tuple[GoalProbeResult, ...]:
    return (
        _natural_flow(),
        _gate_blocked_by_people(),
        _paid_hall_crowded(),
        _gate_unavailable(),
    )


def _natural_flow() -> GoalProbeResult:
    recorder = goal_probe_recorder(
        "natural_flow",
        "自然状态",
        "选择正常闸机，完成排队、服务并进入付费区",
    )
    enter_decision(recorder)
    update_candidates(recorder, 2, (gate("gate_1", walking=3, waiting=2),), "选择正常闸机")
    complete_gate(recorder, "gate_1", start_time=3)
    enter_paid_hall(recorder, 7)
    return recorder.finish(
        {
            "journey_completed": recorder.state.current_node_id == "complete",
            "three_graph_transitions": recorder.state.transition_count == 3,
        }
    )


def _gate_blocked_by_people() -> GoalProbeResult:
    recorder = goal_probe_recorder(
        "gate_blocked_by_people",
        "闸机被其他人堵住",
        "先承诺gate_1，移动停滞后重选gate_2并完成",
    )
    enter_decision(recorder)
    update_candidates(
        recorder,
        2,
        (gate("gate_1", walking=2, waiting=1), gate("gate_2", walking=8, waiting=8)),
        "初次观察选择gate_1",
    )
    recorder.apply(
        GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=3,
            reason="people_blocking_gate_1",
        ),
        "其他乘客挡住接近路径，触发重选",
    )
    update_candidates(
        recorder,
        4,
        (
            gate("gate_1", reachable=False, walking=2, waiting=30),
            gate("gate_2", walking=6, waiting=3),
        ),
        "gate_1暂时不可达，改选gate_2",
    )
    complete_gate(recorder, "gate_2", start_time=5)
    enter_paid_hall(recorder, 9)
    committed = [step.after_facility for step in recorder.steps if step.after_facility]
    return recorder.finish(
        {
            "initial_gate_1": "gate_1" in committed,
            "rerouted_to_gate_2": committed[-1] == "gate_2",
            "retry_recorded": recorder.state.retry_count == 1,
            "journey_completed": recorder.state.current_node_id == "complete",
        }
    )


def _paid_hall_crowded() -> GoalProbeResult:
    recorder = goal_probe_recorder(
        "paid_hall_crowded",
        "闸机后大量人员拥堵",
        "闸机阶段完成后保持付费区目标，不回退到闸机状态",
    )
    enter_decision(recorder)
    update_candidates(recorder, 2, (gate("gate_1", walking=2, waiting=2),), "选择gate_1")
    complete_gate(recorder, "gate_1", start_time=3)
    for time_seconds in (7, 8):
        recorder.apply(
            GoalEvent(
                kind=GoalEventKind.PROGRESS_STALLED.value,
                time_seconds=time_seconds,
                reason="paid_hall_crowding",
            ),
            "付费区拥堵，物理移动无进展；Graph不回退",
        )
    stayed_after_gate = all(
        step.after_node == "enter_paid_hall"
        for step in recorder.steps
        if step.event_kind == GoalEventKind.PROGRESS_STALLED.value
    )
    enter_paid_hall(recorder, 9)
    return recorder.finish(
        {
            "stayed_on_paid_hall_goal": stayed_after_gate,
            "journey_completed_after_clearance": recorder.state.current_node_id == "complete",
        }
    )


def _gate_unavailable() -> GoalProbeResult:
    recorder = goal_probe_recorder(
        "gate_unavailable",
        "闸机无法通过",
        "清除失效承诺；没有可用替代闸机时进入容量等待状态",
    )
    enter_decision(recorder)
    update_candidates(recorder, 2, (gate("gate_1", walking=2, waiting=1),), "选择gate_1")
    recorder.apply(
        GoalEvent(
            kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
            time_seconds=3,
            facility_id="gate_1",
            reason="gate_out_of_service",
        ),
        "闸机故障，撤销承诺",
    )
    update_candidates(
        recorder,
        4,
        (gate("gate_1", available=False, walking=2, waiting=1),),
        "没有可用闸机，保持原地",
    )
    update_candidates(recorder, 5, (), "再次观察仍没有可用闸机")
    return recorder.finish(
        {
            "not_completed": recorder.state.current_node_id == "use_entry_gate",
            "no_invalid_commitment": recorder.state.commitment is None,
            "waiting_for_capacity": recorder.state.interaction_state
            == FacilityInteractionState.WAITING_CAPACITY.value,
        }
    )
