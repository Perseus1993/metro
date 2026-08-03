"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


ScalarMetric = int | float


@runtime_checkable
class ComponentProbeResult(Protocol):
    scenario_id: str
    status: str
    elapsed_seconds: float
    checks: Mapping[str, bool]

    def as_dict(self) -> dict[str, Any]: ...

    def summary_metrics(self) -> Mapping[str, ScalarMetric]: ...


@runtime_checkable
class ComponentProbeScenario(Protocol):
    scenario_id: str

    @property
    def current_time_seconds(self) -> float: ...

    def apply_environment(self) -> None: ...

    def drain_observations(self) -> None: ...

    def is_finished(self) -> bool: ...

    def tick(self) -> None: ...

    def build_result(self, *, timed_out: bool) -> ComponentProbeResult: ...


class ComponentProbeRunner:
    """Run any physical component scenario through one deterministic lifecycle."""

    def run(
        self,
        scenario: ComponentProbeScenario,
        *,
        max_seconds: float,
    ) -> ComponentProbeResult:
        if max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        while scenario.current_time_seconds <= max_seconds:
            scenario.apply_environment()
            scenario.drain_observations()
            if scenario.is_finished():
                return scenario.build_result(timed_out=False)
            scenario.tick()
        return scenario.build_result(timed_out=True)


ScenarioFactory = Callable[[str, int], ComponentProbeScenario]


@dataclass(frozen=True)
class ComponentProbeSuite:
    probe_id: str
    component_ids: tuple[str, ...]
    generated_by: str
    scope: str
    scenario_ids: tuple[str, ...]
    scenario_factory: ScenarioFactory

    def run(self, *, seed: int, max_seconds: float) -> dict[str, Any]:
        results = tuple(
            ComponentProbeRunner().run(
                self.scenario_factory(scenario_id, seed),
                max_seconds=max_seconds,
            )
            for scenario_id in self.scenario_ids
        )
        metrics = _sum_metrics(result.summary_metrics() for result in results)
        return {
            "probe_id": self.probe_id,
            "component_ids": list(self.component_ids),
            "generated_by": self.generated_by,
            "scope": self.scope,
            "seed": seed,
            "summary": {
                "status": "ok" if all(result.status == "ok" for result in results) else "review",
                "scenario_count": len(results),
                "passed_scenarios": sum(result.status == "ok" for result in results),
                **metrics,
            },
            "scenarios": [result.as_dict() for result in results],
        }


def _sum_metrics(
    metrics: Iterable[Mapping[str, ScalarMetric]],
) -> dict[str, ScalarMetric]:
    totals: dict[str, ScalarMetric] = {}
    for scenario_metrics in metrics:
        for name, value in scenario_metrics.items():
            totals[name] = totals.get(name, 0) + value
    return totals
