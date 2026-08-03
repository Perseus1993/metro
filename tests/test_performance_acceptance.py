from __future__ import annotations

import unittest

from metro_station_experiments.performance import (
    PerformanceAcceptancePolicy,
    assess_performance,
)


class PerformanceAcceptanceTests(unittest.TestCase):
    def test_accepts_complete_fast_bounded_run(self) -> None:
        decision = assess_performance(
            {
                "status": "ok",
                "acceptance_status": "pass",
                "population_accounting_error_persons": 0,
                "frame_count": 720,
                "expected_frame_count": 720,
                "memory_profile_status": "ok",
                "memory_profile_frame_count": 720,
                "memory_profile_population_accounting_error_persons": 0,
                "wall_seconds": 10,
                "peak_traced_memory_mb": 100,
                "real_time_factor": 360,
            },
            PerformanceAcceptancePolicy(),
        )

        self.assertEqual("pass", decision["status"])

    def test_rejects_slow_incomplete_memory_heavy_run(self) -> None:
        decision = assess_performance(
            {
                "status": "ok",
                "acceptance_status": "pass",
                "population_accounting_error_persons": 0,
                "frame_count": 719,
                "expected_frame_count": 720,
                "memory_profile_status": "ok",
                "memory_profile_frame_count": 720,
                "memory_profile_population_accounting_error_persons": 0,
                "wall_seconds": 121,
                "peak_traced_memory_mb": 513,
                "real_time_factor": 19,
            },
            PerformanceAcceptancePolicy(),
        )

        self.assertEqual("fail", decision["status"])
        self.assertEqual(4, len(decision["issues"]))

    def test_sustained_load_soak_may_intentionally_skip_scenario_acceptance(self) -> None:
        decision = assess_performance(
            {
                "status": "ok",
                "acceptance_status": "fail",
                "population_accounting_error_persons": 0,
                "frame_count": 720,
                "expected_frame_count": 720,
                "memory_profile_status": "ok",
                "memory_profile_frame_count": 720,
                "memory_profile_population_accounting_error_persons": 0,
                "wall_seconds": 10,
                "peak_traced_memory_mb": 100,
                "real_time_factor": 360,
            },
            PerformanceAcceptancePolicy(require_scenario_acceptance=False),
        )

        self.assertEqual("pass", decision["status"])


if __name__ == "__main__":
    unittest.main()
