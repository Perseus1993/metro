"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import cast

from metro_station.adapters.simulation.planning.default_goal_state_machine import EventDrivenGoalStateMachine
from metro_station.adapters.simulation.planning.goal_engine import GoalEngineResult
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from metro_station.adapters.simulation.planning.journeys import vertical_transfer_journey_graph
from .component_probe import ComponentProbeRunner, ComponentProbeSuite
from .goal_stairs_adapter import GoalStairsObservationAdapter
from .goal_stairs_checks import stairs_probe_checks
from .goal_stairs_command_executor import GoalStairsCommandExecutor
from .goal_stairs_micro_scene import GoalStairsMicroScene
from .goal_stairs_scenario_environment import GoalStairsScenarioEnvironment
from .goal_stairs_trace import GoalStairsProbeResult, GoalStairsTraceStep


STAIRS_SCENARIOS = (
    "natural_descent",
    "entrance_crowded",
    "exit_crowded",
    "stairs_unavailable",
    "no_level_regression",
)


class GoalStairsPhysicalProbe:
    def __init__(self, scenario_id: str, *, seed: int = 42) -> None:
        if scenario_id not in STAIRS_SCENARIOS:
            raise ValueError(f"unsupported stairs goal scenario {scenario_id!r}")
        self.scenario_id = scenario_id
        self.scene = GoalStairsMicroScene(seed=seed)
        self.graph = vertical_transfer_journey_graph()
        self.machine = EventDrivenGoalStateMachine()
        self.observer = GoalStairsObservationAdapter()
        self.executor = GoalStairsCommandExecutor()
        self.traces: list[GoalStairsTraceStep] = []
        self.environment = GoalStairsScenarioEnvironment(scenario_id)
        self._completed_at: float | None = None
        started = self.machine.start(self.graph)
        self.state = started.state
        self.executor.execute(self.scene, started.commands)
        self._record("start", None, started)

    def run(self, *, max_seconds: float = 60.0) -> GoalStairsProbeResult:
        return cast(
            GoalStairsProbeResult,
            ComponentProbeRunner().run(self, max_seconds=max_seconds),
        )

    @property
    def current_time_seconds(self) -> float:
        return self.scene.current_time_seconds

    def apply_environment(self) -> None:
        self.environment.apply(self.scene, self.state)

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

    def is_finished(self) -> bool:
        if self.state.current_node_id == "complete":
            if self.scenario_id != "no_level_regression":
                return True
            if self._completed_at is None:
                self._completed_at = self.current_time_seconds
            return self.current_time_seconds >= self._completed_at + 2.0
        return self.environment.unavailable_wait_finished(self.scene, self.state)

    def tick(self) -> None:
        self.scene.tick()

    def build_result(self, *, timed_out: bool) -> GoalStairsProbeResult:
        checks = stairs_probe_checks(
            self.scenario_id,
            self.scene,
            self.state,
            self.traces,
            completed_at=self._completed_at,
        )
        checks["finished_before_timeout"] = not timed_out
        backend = self.scene.movement_backend
        return GoalStairsProbeResult(
            scenario_id=self.scenario_id,
            status="ok" if checks and all(checks.values()) else "review",
            final_state=self.state.as_dict(),
            final_position=tuple(round(value, 3) for value in self.scene.subject.pos),
            final_level_id=self.scene.subject.current_level_id,
            elapsed_seconds=round(self.current_time_seconds, 3),
            traces=tuple(self.traces),
            checks=checks,
            timed_out=timed_out,
            movement={
                "backend": type(backend).__name__,
                "jupedsim_steps": int(getattr(backend, "jps_step_count", 0)),
                "jupedsim_batches": int(getattr(backend, "jps_batch_count", 0)),
                "vertical_service_events": len(self.scene.facility_service_events),
                "physical_clock": self.scene.simulation_clock.as_dict(),
            },
        )

    def _record(
        self,
        event_kind: str,
        before: AgentGoalState | None,
        result: GoalEngineResult,
    ) -> None:
        subject = self.scene.subject
        self.traces.append(
            GoalStairsTraceStep(
                index=len(self.traces),
                time_seconds=round(self.current_time_seconds, 3),
                event_kind=event_kind,
                handled=result.handled,
                before_graph_state=_state_label(before),
                after_graph_state=_state_label(result.state),
                committed_facility_id=None
                if result.state.commitment is None
                else result.state.commitment.facility_id,
                commands=tuple(command.kind for command in result.commands),
                position=tuple(round(value, 3) for value in subject.pos),
                current_level_id=subject.current_level_id,
                blocker_count=len(self.scene.blockers),
                stair_queues={item.facility_id: item.queue_persons for item in self.scene.stairs},
                active_rides={
                    item.facility_id: item.active_ride_persons for item in self.scene.stairs
                },
            )
        )


def _state_label(state: AgentGoalState | None) -> str:
    if state is None:
        return "none"
    if state.interaction_state is None:
        return state.current_node_id
    return f"{state.current_node_id}/{state.interaction_state}"


def _create_scenario(scenario_id: str, seed: int) -> GoalStairsPhysicalProbe:
    return GoalStairsPhysicalProbe(scenario_id, seed=seed)


GOAL_STAIRS_COMPONENT_PROBE = ComponentProbeSuite(
    probe_id="goal_stairs_physical",
    component_ids=("goal_graph", "stairs_process", "level_transition", "jupedsim_movement"),
    generated_by="GoalStateMachine + Mesa stairs process + JuPedSim micro scene",
    scope="single subject: concourse vertical lobby -> stairs -> platform landing",
    scenario_ids=STAIRS_SCENARIOS,
    scenario_factory=_create_scenario,
)
