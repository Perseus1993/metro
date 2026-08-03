from __future__ import annotations

from dataclasses import asdict, dataclass

from .goal_parity_comparison import compare_goal_event_streams


@dataclass(frozen=True)
class GoalParityEvent:
    passenger_id: int
    stream: str
    kind: str
    time_seconds: float
    stage: str | None = None
    facility_id: str | None = None
    node_id: str | None = None
    reason: str | None = None
    level_id: str | None = None


class GoalParityRecorder:
    """Keep physical and Goal Graph evidence as independent event streams."""

    def __init__(self) -> None:
        self.events: list[GoalParityEvent] = []

    def record(
        self,
        passenger,
        *,
        stream: str,
        kind: str,
        time_seconds: float,
        stage: str | None = None,
        facility_id: str | None = None,
        node_id: str | None = None,
        reason: str | None = None,
        level_id: str | None = None,
    ) -> None:
        event = GoalParityEvent(
            passenger_id=int(passenger.unique_id),
            stream=stream,
            kind=kind,
            time_seconds=float(time_seconds),
            stage=stage,
            facility_id=facility_id,
            node_id=node_id,
            reason=reason,
            level_id=level_id,
        )
        if self.events and self.events[-1] == event:
            return
        self.events.append(event)

    def report(self, model, *, include_events: bool = True) -> dict[str, object]:
        passenger_ids = sorted(model.passenger_goal_runtimes)
        terminal_ids = {event.passenger_id for event in model.passenger_terminal_events}
        complete_ids = {
            passenger_id
            for passenger_id, runtime in model.passenger_goal_runtimes.items()
            if runtime.graph.node(runtime.state.current_node_id).kind == "complete"
        }
        comparisons = compare_goal_event_streams(self.events, passenger_ids)
        report = {
            "checks": {
                "facility_commitments_match": not comparisons["commitment_mismatches"],
                "facility_lifecycle_matches": not comparisons["lifecycle_mismatches"],
                "facility_stage_sequences_match": not comparisons[
                    "stage_sequence_mismatches"
                ],
                "queue_states_match": not comparisons["queue_mismatches"],
                "service_states_match": not comparisons["service_mismatches"],
                "level_transitions_match": not comparisons[
                    "level_transition_mismatches"
                ],
                "replan_reasons_match": not comparisons["replan_mismatches"],
                "graph_complete_implies_physical_terminal": complete_ids <= terminal_ids,
                "physical_terminal_implies_graph_complete": terminal_ids <= complete_ids,
                "no_completed_stage_regressions": not comparisons[
                    "post_terminal_lifecycle_events"
                ],
            },
            **comparisons,
        }
        if include_events:
            report["events"] = [asdict(event) for event in self.events]
        return report

    def record_graph_transition(
        self,
        passenger,
        event,
        before,
        state,
        *,
        skip_selection: bool = False,
    ) -> None:
        if state == before:
            return
        if skip_selection and event.kind == "facility_selected":
            return
        stage = event.stage or before.current_stage or state.current_stage
        self.record(
            passenger,
            stream="graph",
            kind=event.kind,
            time_seconds=event.time_seconds,
            stage=stage,
            facility_id=event.facility_id,
            node_id=state.current_node_id,
            reason=event.reason,
        )
        if event.kind == "service_completed" and before.current_stage == "vertical_transfer":
            self.record(
                passenger,
                stream="graph",
                kind="level_changed",
                time_seconds=event.time_seconds,
                stage=before.current_stage,
                facility_id=event.facility_id,
                node_id=state.current_node_id,
                level_id=getattr(passenger, "current_level_id", None),
            )
