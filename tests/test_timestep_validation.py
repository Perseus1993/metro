from __future__ import annotations

import unittest

from metro_station_experiments.timestep_validation import (
    validate_timestep_candidate,
)


def row(run_id: str, clearance: float, density: float, elapsed: float):
    return {
        "run_id": run_id,
        "clearance_time_seconds": clearance,
        "peak_local_density_persons_m2": density,
        "completion_rate": 1.0,
        "elapsed_seconds": elapsed,
    }


class TimestepValidationTests(unittest.TestCase):
    def test_accepts_close_faster_candidate(self) -> None:
        report = validate_timestep_candidate(
            [row("a", 750, 5.8, 80)],
            [row("a", 735, 5.9, 40)],
        )

        self.assertEqual("pass", report["status"])
        self.assertEqual(2.0, report["elapsed_speedup"])

    def test_rejects_material_drift(self) -> None:
        report = validate_timestep_candidate(
            [row("a", 750, 5.8, 80)],
            [row("a", 650, 6.2, 40)],
        )

        self.assertEqual("fail", report["status"])
        self.assertGreaterEqual(len(report["issues"]), 2)


if __name__ == "__main__":
    unittest.main()
