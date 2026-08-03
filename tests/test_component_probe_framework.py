from __future__ import annotations

import unittest
from dataclasses import asdict, dataclass
from typing import Any

from metro_station_testkit.component_probe import (
    ComponentProbeResult,
    ComponentProbeRunner,
    ComponentProbeScenario,
    ComponentProbeSuite,
)
from metro_station_testkit.goal_gate_physical_probe import (
    GOAL_GATE_COMPONENT_PROBE,
)


@dataclass(frozen=True)
class CountingResult:
    scenario_id: str
    status: str
    elapsed_seconds: float
    checks: dict[str, bool]
    timed_out: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_metrics(self) -> dict[str, int]:
        return {"ticks": int(self.elapsed_seconds)}


class CountingScenario:
    def __init__(self, scenario_id: str, seed: int, *, finish_at: int = 2) -> None:
        self.scenario_id = scenario_id
        self.seed = seed
        self.finish_at = finish_at
        self.time = 0
        self.environment_calls = 0
        self.observation_calls = 0

    @property
    def current_time_seconds(self) -> float:
        return float(self.time)

    def apply_environment(self) -> None:
        self.environment_calls += 1

    def drain_observations(self) -> None:
        self.observation_calls += 1

    def is_finished(self) -> bool:
        return self.time >= self.finish_at

    def tick(self) -> None:
        self.time += 1

    def build_result(self, *, timed_out: bool) -> CountingResult:
        checks = {
            "environment_observed": self.environment_calls > 0,
            "observations_drained": self.observation_calls > 0,
            "finished": self.is_finished(),
        }
        return CountingResult(
            scenario_id=self.scenario_id,
            status="ok" if all(checks.values()) and not timed_out else "review",
            elapsed_seconds=self.current_time_seconds,
            checks=checks,
            timed_out=timed_out,
        )


class ComponentProbeFrameworkTests(unittest.TestCase):
    def test_standalone_component_uses_common_lifecycle(self) -> None:
        scenario = CountingScenario("standalone", seed=7)
        result = ComponentProbeRunner().run(scenario, max_seconds=5.0)

        self.assertIsInstance(scenario, ComponentProbeScenario)
        self.assertIsInstance(result, ComponentProbeResult)
        self.assertEqual("ok", result.status)
        self.assertEqual(2.0, result.elapsed_seconds)

    def test_timeout_is_a_review_result(self) -> None:
        scenario = CountingScenario("timeout", seed=7, finish_at=10)
        result = ComponentProbeRunner().run(scenario, max_seconds=1.0)

        self.assertEqual("review", result.status)
        self.assertTrue(result.timed_out)

    def test_suite_aggregates_scenarios_and_metrics(self) -> None:
        suite = ComponentProbeSuite(
            probe_id="counting",
            component_ids=("counter",),
            generated_by="contract test",
            scope="standalone component",
            scenario_ids=("first", "second"),
            scenario_factory=CountingScenario,
        )
        report = suite.run(seed=3, max_seconds=5.0)

        self.assertEqual("ok", report["summary"]["status"])
        self.assertEqual(2, report["summary"]["scenario_count"])
        self.assertEqual(4, report["summary"]["ticks"])

    def test_gate_suite_declares_joint_component_boundary(self) -> None:
        self.assertEqual(
            ("goal_graph", "gate_process", "jupedsim_movement"),
            GOAL_GATE_COMPONENT_PROBE.component_ids,
        )
        self.assertEqual(4, len(GOAL_GATE_COMPONENT_PROBE.scenario_ids))

    def test_runner_rejects_non_positive_time_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_seconds must be positive"):
            ComponentProbeRunner().run(
                CountingScenario("invalid", seed=1),
                max_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
