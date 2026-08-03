from __future__ import annotations

import unittest
from math import pi

from metro_station_experiments.crowd_safety import crowd_safety_metrics


class CrowdSafetyMetricTests(unittest.TestCase):
    def test_density_counts_groups_on_same_level_within_radius(self) -> None:
        metrics = crowd_safety_metrics(
            [
                {
                    "time_seconds": 10,
                    "passengers": [
                        {"x": 0, "y": 0, "n": 2, "current_level_id": "L1"},
                        {"x": 0.5, "y": 0, "n": 1, "current_level_id": "L1"},
                        {"x": 0, "y": 0, "n": 9, "current_level_id": "L2"},
                    ],
                }
            ],
            radius_m=1.0,
            tick_seconds=5.0,
            threshold_persons_m2=0.5,
        )

        self.assertAlmostEqual(9 / pi, metrics["peak_local_density_persons_m2"], places=6)
        self.assertEqual(10.0, metrics["peak_local_density_time_seconds"])
        self.assertEqual("L2", metrics["peak_local_density_level_id"])
        self.assertEqual(0.0, metrics["peak_local_density_x"])
        self.assertEqual(0.0, metrics["peak_local_density_y"])
        self.assertEqual(1, metrics["frames_above_density_threshold"])
        self.assertEqual(60.0, metrics["density_exposure_person_seconds"])

    def test_empty_frames_and_exact_threshold_are_not_above_limit(self) -> None:
        exact_density = 1 / pi
        metrics = crowd_safety_metrics(
            [{"time_seconds": 0, "passengers": [{"x": 0, "y": 0, "n": 1}]}],
            radius_m=1.0,
            tick_seconds=1.0,
            threshold_persons_m2=exact_density,
        )

        self.assertEqual(0, metrics["frames_above_density_threshold"])
        self.assertEqual(0.0, metrics["duration_above_density_threshold_seconds"])

    def test_non_finite_or_non_positive_inputs_fail(self) -> None:
        for radius in (0, -1, float("nan"), float("inf")):
            with self.subTest(radius=radius):
                with self.assertRaises(ValueError):
                    crowd_safety_metrics([], radius_m=radius, tick_seconds=1)


if __name__ == "__main__":
    unittest.main()
