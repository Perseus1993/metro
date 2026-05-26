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

    @classmethod
    def from_scenario(cls, scenario: StationSandboxScenario, rng: Any) -> "DemandScheduler":
        return cls(scenario, rng)

    def due_by_intent(self, step_index: int) -> Counter[str]:
        due = self.spawn_schedule.get(step_index, Counter())
        if isinstance(due, int):
            return Counter({AgentIntent.ENTER_AND_BOARD.value: due})
        return Counter(due)

    def _build_spawn_schedule(self) -> dict[int, Counter[str]]:
        schedule: dict[int, Counter[str]] = defaultdict(Counter)
        self._add_intent_spawn_schedule(
            schedule,
            AgentIntent.ENTER_AND_BOARD.value,
            self.scenario.entry_groups,
        )
        self._add_intent_spawn_schedule(
            schedule,
            AgentIntent.EXIT_STATION.value,
            self.scenario.exit_groups,
        )
        return dict(schedule)

    def _add_intent_spawn_schedule(
        self,
        schedule: dict[int, Counter[str]],
        intent: str,
        groups: int,
    ) -> None:
        if groups <= 0:
            return
        ticks = self.scenario.horizon_steps
        last_spawn_step = max(0, ticks - 2)
        for index in range(groups):
            base = index * ticks / groups
            jitter = self.random.uniform(-0.35, 0.35) * ticks / groups
            step = max(0, min(last_spawn_step, int(round(base + jitter))))
            schedule[step][intent] += 1
