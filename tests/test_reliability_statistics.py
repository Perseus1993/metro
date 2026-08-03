from __future__ import annotations

import unittest

from metro_station_experiments.reliability import (
    bootstrap_mean_interval,
    percentile,
    reliability_report,
)


class ReliabilityStatisticsTests(unittest.TestCase):
    def test_percentile_interpolates_exact_boundaries(self) -> None:
        self.assertEqual(1.0, percentile([1, 2, 3], 0.0))
        self.assertEqual(2.0, percentile([1, 2, 3], 0.5))
        self.assertEqual(3.0, percentile([1, 2, 3], 1.0))
        self.assertEqual(2.5, percentile([1, 2, 3, 4], 0.5))

    def test_bootstrap_interval_is_deterministic_and_contains_constant(self) -> None:
        first = bootstrap_mean_interval([5, 5, 5], samples=100, seed=7)
        second = bootstrap_mean_interval([5, 5, 5], samples=100, seed=7)

        self.assertEqual((5.0, 5.0), first)
        self.assertEqual(first, second)

    def test_report_requires_minimum_samples_per_population(self) -> None:
        rows = [
            {
                "initial_persons": 60,
                "status": "ok",
                "acceptance_status": "pass",
                "clearance_time_seconds": 200 + seed,
                "peak_local_density_persons_m2": 4 + seed / 100,
            }
            for seed in range(3)
        ]

        report = reliability_report(rows, min_samples=30, bootstrap_samples=100)

        self.assertEqual("insufficient", report["status"])
        self.assertEqual(3, report["groups"][0]["sample_count"])
        self.assertEqual("reliability.insufficient_samples", report["blockers"][0]["code"])

    def test_failed_run_blocks_even_with_enough_samples(self) -> None:
        rows = [
            {
                "initial_persons": 60,
                "status": "ok",
                "acceptance_status": "fail" if seed == 0 else "pass",
                "clearance_time_seconds": 200,
                "peak_local_density_persons_m2": 4,
            }
            for seed in range(30)
        ]

        report = reliability_report(rows, min_samples=30, bootstrap_samples=100)

        self.assertEqual("fail", report["status"])
        self.assertEqual(1, report["groups"][0]["acceptance_failures"])


if __name__ == "__main__":
    unittest.main()
