from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.calibration.validation import (
    CalibrationValidationPolicy,
    missing_calibration_evidence,
    validate_calibration,
)


def rows(clearances: list[float], densities: list[float]) -> list[dict[str, float | str]]:
    return [
        {
            "run_id": f"case_{index}",
            "clearance_time_seconds": clearance,
            "peak_local_density_persons_m2": density,
        }
        for index, (clearance, density) in enumerate(zip(clearances, densities))
    ]


class CalibrationValidationTests(unittest.TestCase):
    def test_passes_independent_well_matched_evidence(self) -> None:
        observed = rows([100, 110], [3.0, 3.2])
        simulated = rows([105, 108], [3.1, 3.0])

        report = validate_calibration(
            simulated,
            observed,
            calibration_dataset_id="calibration_day",
            validation_dataset_id="validation_day",
            policy=CalibrationValidationPolicy(min_matched_cases=2),
        )

        self.assertEqual("pass", report["status"])
        self.assertEqual(3.5, report["metrics"]["clearance_time_seconds"]["mae"])

    def test_rejects_non_independent_and_bad_fit(self) -> None:
        observed = rows([100], [3.0])
        simulated = rows([200], [5.0])

        report = validate_calibration(
            simulated,
            observed,
            calibration_dataset_id="same",
            validation_dataset_id="same",
            policy=CalibrationValidationPolicy(min_matched_cases=1),
        )

        self.assertEqual("fail", report["status"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("calibration.datasets_not_independent", codes)
        self.assertIn("calibration.clearance_mae", codes)
        self.assertIn("calibration.density_mae", codes)

    def test_missing_evidence_is_blocked(self) -> None:
        report = missing_calibration_evidence("no observed file")

        self.assertEqual("blocked", report["status"])
        self.assertEqual("calibration.observed_data_missing", report["issues"][0]["code"])


if __name__ == "__main__":
    unittest.main()
