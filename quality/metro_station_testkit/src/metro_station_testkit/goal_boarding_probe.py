"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import cast

from metro_station.adapters.simulation.planning.default_goal_state_machine import EventDrivenGoalStateMachine
from metro_station.adapters.simulation.planning.goal_engine import GoalEngineResult
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from metro_station.adapters.simulation.planning.journeys import boarding_journey_graph
from .component_probe import ComponentProbeRunner, ComponentProbeSuite
from .goal_boarding_adapter import GoalBoardingObservationAdapter
from .goal_boarding_checks import boarding_probe_checks
from .goal_boarding_command_executor import GoalBoardingCommandExecutor
from .goal_boarding_micro_scene import GoalBoardingMicroScene
from .goal_boarding_scenario_environment import GoalBoardingScenarioEnvironment
from .goal_boarding_trace import GoalBoardingProbeResult, GoalBoardingTraceStep


BOARDING_SCENARIOS = (
    "natural_boarding",
    "door_front_crowded",
    "alighting_conflict",
    "train_full",
    "train_not_open",
    "no_platform_return",
)


class GoalBoardingPhysicalProbe:
    def __init__(self, scenario_id: str, *, seed: int = 42) -> None:
        if scenario_id not in BOARDING_SCENARIOS:
            raise ValueError(f"unsupported boarding goal scenario {scenario_id!r}")
        self.scenario_id = scenario_id
        self.scene = GoalBoardingMicroScene(seed=seed)
        self.graph = boarding_journey_graph()
        self.machine = EventDrivenGoalStateMachine()
        self.observer = GoalBoardingObservationAdapter()
        self.executor = GoalBoardingCommandExecutor()
        self.environment = GoalBoardingScenarioEnvironment(scenario_id)
        self.traces: list[GoalBoardingTraceStep] = []
        self._completed_at: float | None = None
        started = self.machine.start(self.graph)
        self.state = started.state
        self.executor.execute(self.scene, started.commands)
        self._record("start", None, started)

    def run(self, *, max_seconds: float = 60.0) -> GoalBoardingProbeResult:
        return cast(
            GoalBoardingProbeResult,
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
            if self.scenario_id != "no_platform_return":
                return True
            if self._completed_at is None:
                self._completed_at = self.current_time_seconds
            return self.current_time_seconds >= self._completed_at + 2.0
        return self.environment.blocked_scenario_finished(self.scene, self.state)

    def tick(self) -> None:
        self.scene.tick()

    def build_result(self, *, timed_out: bool) -> GoalBoardingProbeResult:
        checks = boarding_probe_checks(
            self.scenario_id,
            self.scene,
            self.state,
            self.traces,
            completed_at=self._completed_at,
        )
        checks["finished_before_timeout"] = not timed_out
        backend = self.scene.movement_backend
        return GoalBoardingProbeResult(
            scenario_id=self.scenario_id,
            status="ok" if checks and all(checks.values()) else "review",
            final_state=self.state.as_dict(),
            final_passenger_state=self.scene.subject.state,
            elapsed_seconds=round(self.current_time_seconds, 3),
            traces=tuple(self.traces),
            checks=checks,
            timed_out=timed_out,
            movement={
                "backend": type(backend).__name__,
                "jupedsim_steps": int(getattr(backend, "jps_step_count", 0)),
                "jupedsim_batches": int(getattr(backend, "jps_batch_count", 0)),
                "boarding_service_events": len(self.scene.facility_service_events),
                "boarded_persons": self.scene.boarded_persons,
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
        train = self.scene.train
        self.traces.append(
            GoalBoardingTraceStep(
                index=len(self.traces),
                time_seconds=round(self.current_time_seconds, 3),
                event_kind=event_kind,
                before_graph_state=_state_label(before),
                after_graph_state=_state_label(result.state),
                committed_facility_id=None
                if result.state.commitment is None
                else result.state.commitment.facility_id,
                commands=tuple(command.kind for command in result.commands),
                position=tuple(round(value, 3) for value in subject.pos),
                passenger_state=subject.state,
                train_state=train.state,
                train_load=train.current_load_persons,
                train_capacity_remaining=train.capacity_remaining,
                blocker_count=len(self.scene.blockers),
                door_queues={door.facility_id: door.queue_persons for door in self.scene.doors},
            )
        )


def _state_label(state: AgentGoalState | None) -> str:
    if state is None:
        return "none"
    if state.interaction_state is None:
        return state.current_node_id
    return f"{state.current_node_id}/{state.interaction_state}"


def _create_scenario(scenario_id: str, seed: int) -> GoalBoardingPhysicalProbe:
    return GoalBoardingPhysicalProbe(scenario_id, seed=seed)


GOAL_BOARDING_COMPONENT_PROBE = ComponentProbeSuite(
    probe_id="goal_boarding_physical",
    component_ids=(
        "goal_graph",
        "boarding_door_process",
        "train_dwell_capacity",
        "jupedsim_movement",
    ),
    generated_by="GoalStateMachine + Mesa train/door process + JuPedSim micro scene",
    scope="single subject: platform decision area -> train door queue -> boarded",
    scenario_ids=BOARDING_SCENARIOS,
    scenario_factory=_create_scenario,
)
