from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..planning.plan import AgentIntent
from ..station.scenario import StationSandboxScenario


class DemandScheduler:
    """Build and expose passenger demand due for each simulation step."""

    def __init__(self, scenario: StationSandboxScenario, rng: Any) -> None:
        self.scenario = scenario
        self.random = rng
        self.spawn_schedule = self._build_spawn_schedule()
        self.alighting_schedule = self._build_alighting_schedule()

    @classmethod
    def from_scenario(cls, scenario: StationSandboxScenario, rng: Any) -> "DemandScheduler":
        return cls(scenario, rng)

    def due_by_intent(self, step_index: int) -> Counter[str]:
        due = self.spawn_schedule.get(step_index, Counter())
        if isinstance(due, int):
            return Counter({AgentIntent.ENTER_AND_BOARD.value: due})
        return Counter(due)

    def due_alightings(self, step_index: int) -> int:
        return int(self.alighting_schedule.get(step_index, 0))

    def _build_spawn_schedule(self) -> dict[int, Counter[str]]:
        schedule: dict[int, Counter[str]] = defaultdict(Counter)
        self._add_intent_spawn_schedule(
            schedule,
            AgentIntent.ENTER_AND_BOARD.value,
            self.scenario.entry_groups,
        )
        return dict(schedule)

    def _build_alighting_schedule(self) -> dict[int, int]:
        schedule: dict[int, int] = defaultdict(int)
        release_steps = self._train_dwell_release_steps()
        if not release_steps:
            return {}

        for index in range(self.scenario.exit_groups):
            step = release_steps[index * len(release_steps) // self.scenario.exit_groups]
            schedule[step] += 1
        return dict(schedule)

    def _add_intent_spawn_schedule(
        self,
        schedule: dict[int, Counter[str]],
        intent: str,
        groups: int,
    ) -> None:
        if groups <= 0:
            return
        ticks = self.scenario.demand_steps
        last_spawn_step = max(0, ticks - 2)
        for index in range(groups):
            base = index * ticks / groups
            jitter = self.random.uniform(-0.35, 0.35) * ticks / groups
            step = max(0, min(last_spawn_step, int(round(base + jitter))))
            schedule[step][intent] += 1

    def _train_dwell_release_steps(self) -> list[int]:
        if self.scenario.exit_groups <= 0:
            return []

        arrivals = self._train_arrival_steps_for_exit_demand()
        dwell_steps = max(1, round(self.scenario.train_dwell_seconds / self.scenario.tick_seconds))
        release_steps: list[int] = []
        for arrival_step in arrivals:
            for offset in range(dwell_steps):
                step = arrival_step + offset
                if step >= self.scenario.horizon_steps:
                    break
                release_steps.append(step)
        return release_steps

    def _train_arrival_steps_for_exit_demand(self) -> list[int]:
        first_arrival_step = max(
            1,
            round(self.scenario.initial_train_offset_seconds / self.scenario.tick_seconds),
        )
        if first_arrival_step >= self.scenario.horizon_steps:
            return []

        headway_steps = max(1, round(self.scenario.train_headway_seconds / self.scenario.tick_seconds))
        arrivals: list[int] = []
        step = first_arrival_step
        while step < self.scenario.horizon_steps:
            if step <= self.scenario.demand_steps:
                arrivals.append(step)
            step += headway_steps

        return arrivals or [first_arrival_step]
