"""Goal Graph probe migrated from the planning production namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import DecisionObservation, FacilityObservation, GoalEvent, GoalEventKind
from .goal_probe import GoalProbeRecorder
from metro_station.adapters.simulation.planning.journeys import entry_gate_journey_graph


def goal_probe_recorder(scenario_id: str, label: str, outcome: str) -> GoalProbeRecorder:
    return GoalProbeRecorder(
        scenario_id=scenario_id,
        label=label,
        expected_outcome=outcome,
        graph=entry_gate_journey_graph(),
    )


def enter_decision(recorder: GoalProbeRecorder) -> None:
    recorder.apply(
        GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=1,
            region_id="entry_gate_decision",
        ),
        "进入闸机决策区，此时尚未绑定具体闸机",
    )


def update_candidates(
    recorder: GoalProbeRecorder,
    time_seconds: float,
    candidates: tuple[FacilityObservation, ...],
    note: str,
) -> None:
    observation = DecisionObservation(
        time_seconds=time_seconds,
        current_region_id="entry_gate_decision",
        entered_region_ids=("entry_gate_decision",),
        candidates=candidates,
    )
    recorder.apply(
        GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=time_seconds,
            observation=observation,
        ),
        note,
    )


def complete_gate(recorder: GoalProbeRecorder, facility_id: str, *, start_time: int) -> None:
    events = (
        (GoalEventKind.REACHED_QUEUE_CAPTURE, "到达动态队尾捕获区"),
        (GoalEventKind.QUEUE_JOINED, "正式进入闸机队列"),
        (GoalEventKind.SERVICE_STARTED, "开始通过闸机"),
        (GoalEventKind.SERVICE_COMPLETED, "完成闸机服务，目标切换到付费区"),
    )
    for offset, (kind, note) in enumerate(events):
        recorder.apply(
            GoalEvent(
                kind=kind.value,
                time_seconds=start_time + offset,
                facility_id=facility_id,
            ),
            note,
        )


def enter_paid_hall(recorder: GoalProbeRecorder, time_seconds: float) -> None:
    recorder.apply(
        GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=time_seconds,
            region_id="paid_hall",
        ),
        "进入付费区，最小旅程完成",
    )


def gate(
    facility_id: str,
    *,
    available: bool = True,
    reachable: bool = True,
    walking: float,
    waiting: float,
) -> FacilityObservation:
    return FacilityObservation(
        facility_id=facility_id,
        stage="entry_gate",
        available=available,
        reachable=reachable,
        walking_time_seconds=walking,
        queue_persons=0,
        estimated_wait_seconds=waiting,
    )
