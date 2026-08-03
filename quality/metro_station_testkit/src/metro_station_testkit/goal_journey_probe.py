"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from typing import cast

from metro_station.adapters.simulation.planning.default_goal_state_machine import EventDrivenGoalStateMachine
from metro_station.adapters.simulation.planning.goal_engine import GoalEngineResult
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState
from metro_station.adapters.simulation.planning.journeys import station_entry_to_boarding_journey_graph
from .component_probe import ComponentProbeRunner, ComponentProbeSuite
from .goal_journey_adapter import GoalJourneyObservationAdapter
from .goal_journey_checks import journey_probe_checks
from .goal_journey_command_executor import GoalJourneyCommandExecutor
from .goal_journey_crowd import populate_journey_crowd
from .goal_journey_micro_scene import GoalJourneyMicroScene
from .goal_journey_scenario_environment import GoalJourneyScenarioEnvironment
from .goal_journey_trace import GoalJourneyProbeResult, GoalJourneyTraceStep


JOURNEY_SCENARIOS = (
    "natural_full_journey",
    "crowded_full_journey",
    "gate_replan",
    "stairs_replan",
    "door_replan",
    "delayed_train",
    "train_full_after_full_journey",
    "no_stage_regression",
)


class GoalJourneyPhysicalProbe:
    def __init__(self, scenario_id: str, *, seed: int = 42) -> None:
        if scenario_id not in JOURNEY_SCENARIOS:
            raise ValueError(f"unsupported full journey scenario {scenario_id!r}")
        self.scenario_id = scenario_id
        self.scene = GoalJourneyMicroScene(seed=seed)
        if scenario_id == "crowded_full_journey":
            populate_journey_crowd(self.scene)
        self.graph = station_entry_to_boarding_journey_graph()
        self.machine = EventDrivenGoalStateMachine()
        self.observer = GoalJourneyObservationAdapter()
        self.executor = GoalJourneyCommandExecutor()
        self.environment = GoalJourneyScenarioEnvironment(scenario_id)
        self.traces: list[GoalJourneyTraceStep] = []
        self.physical_frames: list[dict[str, object]] = []
        self._completed_at: float | None = None
        started = self.machine.start(self.graph)
        self.state = started.state
        self.executor.execute(
            self.scene,
            started.commands,
            current_stage=self.state.current_stage,
        )
        self._record("start", None, started)
        self._record_physical_frame()

    def run(self, *, max_seconds: float = 120.0) -> GoalJourneyProbeResult:
        return cast(
            GoalJourneyProbeResult,
            ComponentProbeRunner().run(self, max_seconds=max_seconds),
        )

    @property
    def current_time_seconds(self) -> float:
        return self.scene.current_time_seconds

    def apply_environment(self) -> None:
        self.environment.apply(self.scene, self.state)

    def drain_observations(self) -> None:
        for _ in range(10):
            event = self.observer.observe(self.scene, self.graph, self.state)
            if event is None:
                return
            before = self.state
            result = self.machine.handle(self.graph, before, event)
            self.state = result.state
            self.executor.execute(
                self.scene,
                result.commands,
                current_stage=self.state.current_stage,
            )
            self._record(event.kind, before, result)
            if any(
                command.kind == "complete_journey" for command in result.commands
            ):
                self._record_physical_frame()
            self.apply_environment()

    def is_finished(self) -> bool:
        if self.state.current_node_id == "complete":
            if self.scenario_id != "no_stage_regression":
                return True
            if self._completed_at is None:
                self._completed_at = self.current_time_seconds
            return self.current_time_seconds >= self._completed_at + 2.0
        return self.environment.full_train_finished(self.scene, self.state)

    def tick(self) -> None:
        self.scene.tick()
        self._record_physical_frame()

    def build_result(self, *, timed_out: bool) -> GoalJourneyProbeResult:
        checks = journey_probe_checks(
            self.scenario_id,
            self.scene,
            self.state,
            self.traces,
            completed_at=self._completed_at,
        )
        checks["finished_before_timeout"] = not timed_out
        backend = self.scene.movement_backend
        return GoalJourneyProbeResult(
            scenario_id=self.scenario_id,
            status="ok" if checks and all(checks.values()) else "review",
            final_state=self.state.as_dict(),
            final_passenger_state=self.scene.subject.state,
            final_level_id=self.scene.subject.current_level_id,
            elapsed_seconds=round(self.current_time_seconds, 3),
            traces=tuple(self.traces),
            checks=checks,
            timed_out=timed_out,
            movement={
                "backend": type(backend).__name__,
                "jupedsim_steps": int(getattr(backend, "jps_step_count", 0)),
                "jupedsim_batches": int(getattr(backend, "jps_batch_count", 0)),
                "facility_service_events": len(self.scene.facility_service_events),
                "service_kinds": [
                    event.facility_kind for event in self.scene.facility_service_events
                ],
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
            GoalJourneyTraceStep(
                index=len(self.traces),
                time_seconds=round(self.current_time_seconds, 3),
                event_kind=event_kind,
                before_graph_state=_state_label(before),
                after_graph_state=_state_label(result.state),
                current_stage=result.state.current_stage,
                committed_facility_id=None
                if result.state.commitment is None
                else result.state.commitment.facility_id,
                commands=tuple(command.kind for command in result.commands),
                position=tuple(round(value, 3) for value in subject.pos),
                level_id=subject.current_level_id,
                passenger_state=subject.state,
                train_state=train.state,
                train_load=train.current_load_persons,
                blocker_count=len(self.scene.blockers),
                service_event_count=len(self.scene.facility_service_events),
            )
        )

    def _record_physical_frame(self) -> None:
        subject = self.scene.subject
        self.physical_frames.append(
            {
                "time_seconds": round(self.current_time_seconds, 3),
                "position": [round(value, 3) for value in subject.pos],
                "target": [round(value, 3) for value in subject.target],
                "level_id": subject.current_level_id,
                "passenger_state": subject.state,
                "train_state": self.scene.train.state,
                "train_load": self.scene.train.current_load_persons,
                "service_event_count": len(self.scene.facility_service_events),
                "crowd": [
                    [
                        int(item.unique_id),
                        round(item.pos[0], 3),
                        round(item.pos[1], 3),
                        item.current_level_id,
                        "flow",
                    ]
                    for item in self.scene.crowd
                ]
                + [
                    [
                        int(item.unique_id),
                        round(item.pos[0], 3),
                        round(item.pos[1], 3),
                        item.current_level_id,
                        "blocker",
                    ]
                    for item in self.scene.blockers
                ],
            }
        )


def _state_label(state: AgentGoalState | None) -> str:
    if state is None:
        return "none"
    if state.interaction_state is None:
        return state.current_node_id
    return f"{state.current_node_id}/{state.interaction_state}"


def _create_scenario(scenario_id: str, seed: int) -> GoalJourneyPhysicalProbe:
    return GoalJourneyPhysicalProbe(scenario_id, seed=seed)


GOAL_JOURNEY_COMPONENT_PROBE = ComponentProbeSuite(
    probe_id="goal_station_entry_to_boarding",
    component_ids=(
        "goal_graph",
        "gate_process",
        "stairs_process",
        "level_transition",
        "boarding_door_process",
        "train_dwell_capacity",
        "jupedsim_movement",
    ),
    generated_by="GoalStateMachine + Mesa facilities/train + JuPedSim full micro journey",
    scope="single subject: entrance -> gate -> stairs -> platform -> train",
    scenario_ids=JOURNEY_SCENARIOS,
    scenario_factory=_create_scenario,
)
