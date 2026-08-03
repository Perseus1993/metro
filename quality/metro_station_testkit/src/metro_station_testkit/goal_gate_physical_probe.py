"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import cast

from metro_station.adapters.simulation.planning.default_goal_state_machine import EventDrivenGoalStateMachine
from metro_station.adapters.simulation.planning.goal_engine import GoalEngineResult
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from metro_station.adapters.simulation.planning.journeys import entry_gate_journey_graph
from .component_probe import ComponentProbeRunner, ComponentProbeSuite
from .goal_gate_adapter import GoalGateObservationAdapter
from .goal_gate_command_executor import GoalGateCommandExecutor
from .goal_gate_micro_scene import GoalGateMicroScene
from .goal_gate_physical_trace import GoalPhysicalProbeResult, GoalPhysicalTraceStep


PHYSICAL_SCENARIOS = (
    "natural_flow",
    "gate_blocked_by_people",
    "paid_hall_crowded",
    "gate_unavailable",
)


class GoalGatePhysicalProbe:
    def __init__(self, scenario_id: str, *, seed: int = 42) -> None:
        if scenario_id not in PHYSICAL_SCENARIOS:
            raise ValueError(f"unsupported physical goal scenario {scenario_id!r}")
        self.scenario_id = scenario_id
        self.scene = GoalGateMicroScene(seed=seed)
        self.graph = entry_gate_journey_graph()
        self.machine = EventDrivenGoalStateMachine()
        self.observer = GoalGateObservationAdapter()
        self.executor = GoalGateCommandExecutor()
        self.traces: list[GoalPhysicalTraceStep] = []
        self.environment_actions: set[str] = set()
        started = self.machine.start(self.graph)
        self.state = started.state
        self.executor.execute(self.scene, started.commands)
        self._record("start", None, started)

    def run(self, *, max_seconds: float = 50.0) -> GoalPhysicalProbeResult:
        return cast(
            GoalPhysicalProbeResult,
            ComponentProbeRunner().run(self, max_seconds=max_seconds),
        )

    @property
    def current_time_seconds(self) -> float:
        return self.scene.current_time_seconds

    def build_result(self, *, timed_out: bool) -> GoalPhysicalProbeResult:
        checks = self._checks()
        checks["finished_before_timeout"] = not timed_out
        backend = self.scene.movement_backend
        return GoalPhysicalProbeResult(
            scenario_id=self.scenario_id,
            status="ok" if checks and all(checks.values()) else "review",
            final_state=self.state.as_dict(),
            final_position=tuple(round(value, 3) for value in self.scene.subject.pos),
            elapsed_seconds=round(self.scene.current_time_seconds, 3),
            traces=tuple(self.traces),
            checks=checks,
            timed_out=timed_out,
            movement={
                "backend": type(backend).__name__,
                "jupedsim_steps": int(getattr(backend, "jps_step_count", 0)),
                "jupedsim_batches": int(getattr(backend, "jps_batch_count", 0)),
                "physical_clock": self.scene.simulation_clock.as_dict(),
            },
        )

    def drain_observations(self) -> None:
        for _ in range(8):
            event = self.observer.observe(self.scene, self.graph, self.state)
            if event is None:
                return
            before = self.state
            result = self.machine.handle(self.graph, before, event)
            self.state = result.state
            self.executor.execute(self.scene, result.commands)
            self._record(event.kind, before, result)
            self.apply_environment()

    def apply_environment(self) -> None:
        if self.scenario_id == "gate_blocked_by_people":
            if self._committed_to("gate_1") and "gate_crowd_added" not in self.environment_actions:
                gate = self.scene.gates_by_id["gate_1"]
                self.scene.add_blocker_cluster(gate.spec.queue_anchor)
                self.environment_actions.add("gate_crowd_added")
        elif self.scenario_id == "paid_hall_crowded":
            if self.state.current_node_id == "enter_paid_hall":
                if "paid_crowd_added" not in self.environment_actions:
                    self.scene.add_blocker_cluster(self.scene.paid_hall_position, rows=3, columns=5)
                    self.environment_actions.add("paid_crowd_added")
                    self._paid_crowd_start = self.scene.current_time_seconds
                elif (
                    "paid_crowd_cleared" not in self.environment_actions
                    and self.scene.current_time_seconds >= self._paid_crowd_start + 3.0
                ):
                    self.scene.clear_blockers()
                    self.environment_actions.add("paid_crowd_cleared")
        elif self.scenario_id == "gate_unavailable":
            if self.state.commitment is not None and "gates_disabled" not in self.environment_actions:
                self.scene.disabled_gate_ids.update(self.scene.gates_by_id)
                self.environment_actions.add("gates_disabled")
                self._disabled_at = self.scene.current_time_seconds

    def is_finished(self) -> bool:
        if self.state.current_node_id == "complete":
            return True
        return (
            self.scenario_id == "gate_unavailable"
            and "gates_disabled" in self.environment_actions
            and self.scene.current_time_seconds >= self._disabled_at + 3.0
            and self.state.interaction_state
            == FacilityInteractionState.EVALUATE_CANDIDATES.value
            and self.state.commitment is None
        )

    def tick(self) -> None:
        self.scene.tick()

    def _checks(self) -> dict[str, bool]:
        completed = self.state.current_node_id == "complete"
        facilities = [trace.committed_facility_id for trace in self.traces]
        stalls = [trace for trace in self.traces if trace.event_kind == "progress_stalled"]
        if self.scenario_id == "natural_flow":
            return {"completed": completed, "no_retry": self.state.retry_count == 0}
        if self.scenario_id == "gate_blocked_by_people":
            return {
                "completed": completed,
                "selected_gate_1": "gate_1" in facilities,
                "rerouted_gate_2": "gate_2" in facilities,
                "physical_blockers_present": any(trace.blocker_count > 0 for trace in self.traces),
                "stall_emitted": bool(stalls),
            }
        if self.scenario_id == "paid_hall_crowded":
            return {
                "completed_after_clearance": completed,
                "stalled_on_paid_hall_goal": bool(stalls)
                and all(trace.after_graph_state.startswith("enter_paid_hall") for trace in stalls),
            }
        return {
            "not_completed": not completed,
            "uncommitted": self.state.commitment is None,
            "waiting_for_candidates": self.state.interaction_state
            == FacilityInteractionState.EVALUATE_CANDIDATES.value,
        }

    def _committed_to(self, facility_id: str) -> bool:
        return self.state.commitment is not None and self.state.commitment.facility_id == facility_id

    def _record(
        self,
        event_kind: str,
        before: AgentGoalState | None,
        result: GoalEngineResult,
    ) -> None:
        subject = self.scene.subject
        self.traces.append(
            GoalPhysicalTraceStep(
                index=len(self.traces),
                time_seconds=round(self.scene.current_time_seconds, 3),
                event_kind=event_kind,
                handled=result.handled,
                before_graph_state=_state_label(before),
                after_graph_state=_state_label(result.state),
                committed_facility_id=None
                if result.state.commitment is None
                else result.state.commitment.facility_id,
                commands=tuple(command.kind for command in result.commands),
                position=tuple(round(value, 3) for value in subject.pos),
                target=tuple(round(value, 3) for value in subject.target),
                blocker_count=len(self.scene.blockers),
                gate_queues={gate.facility_id: gate.queue_persons for gate in self.scene.gates},
            )
        )


def _state_label(state: AgentGoalState | None) -> str:
    if state is None:
        return "none"
    return (
        state.current_node_id
        if state.interaction_state is None
        else f"{state.current_node_id}/{state.interaction_state}"
    )


def _create_scenario(scenario_id: str, seed: int) -> GoalGatePhysicalProbe:
    return GoalGatePhysicalProbe(scenario_id, seed=seed)


GOAL_GATE_COMPONENT_PROBE = ComponentProbeSuite(
    probe_id="goal_gate_physical",
    component_ids=("goal_graph", "gate_process", "jupedsim_movement"),
    generated_by="GoalStateMachine + Mesa gate process + JuPedSim micro scene",
    scope="single subject: station entrance -> entry gate -> paid hall",
    scenario_ids=PHYSICAL_SCENARIOS,
    scenario_factory=_create_scenario,
)
