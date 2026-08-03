from __future__ import annotations

import unittest

from metro_station_experiments.emergency_acceptance import (
    EmergencyAcceptancePolicy,
    assess_emergency_row,
)


class EmergencyAcceptanceTests(unittest.TestCase):
    def test_exact_thresholds_pass_and_just_over_limits_fail(self) -> None:
        row = {
            "status": "ok",
            "completion_rate": 0.95,
            "clearance_time_seconds": 300,
            "remaining_persons": 1,
            "peak_local_density_persons_m2": 4.0,
            "population_accounting_error_persons": 0,
        }
        exact = assess_emergency_row(
            row,
            EmergencyAcceptancePolicy(0.95, 300, 1, 4.0),
        )
        over = assess_emergency_row(
            row,
            EmergencyAcceptancePolicy(0.9501, 299.9, 0, 3.999),
        )

        self.assertEqual("pass", exact["acceptance_status"])
        self.assertEqual("fail", over["acceptance_status"])
        self.assertEqual(4, len(over["acceptance_issues"]))

    def test_invariant_failure_blocks_without_optional_thresholds(self) -> None:
        decision = assess_emergency_row(
            {
                "status": "ok",
                "population_accounting_error_persons": 1,
                "active_service_stranded_persons_final": 2,
                "facility_service_start_violations": 1,
                "train_arrival_during_suspension_violations": 1,
            },
            EmergencyAcceptancePolicy(),
        )

        self.assertEqual("fail", decision["acceptance_status"])
        self.assertEqual(4, len(decision["acceptance_issues"]))

    def test_incomplete_evacuation_fails_clearance_threshold(self) -> None:
        decision = assess_emergency_row(
            {"status": "ok", "completion_rate": 0.8, "clearance_time_seconds": None},
            EmergencyAcceptancePolicy(max_clearance_seconds=600),
        )

        self.assertEqual("fail", decision["acceptance_status"])
        self.assertIn("incomplete", decision["acceptance_issues"][0])


if __name__ == "__main__":
    unittest.main()
