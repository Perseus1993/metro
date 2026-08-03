from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.calibration.contracts import (
    CALIBRATED,
    UNCALIBRATED,
    VALIDATED,
    CalibrationProfile,
)


class CalibrationContractTests(unittest.TestCase):
    def test_default_profile_is_runnable_but_not_research_ready(self) -> None:
        profile = CalibrationProfile()

        self.assertEqual(UNCALIBRATED, profile.status)
        self.assertFalse(profile.research_ready)
        self.assertFalse(profile.as_dict()["research_ready"])

    def test_calibrated_profile_requires_calibration_dataset(self) -> None:
        with self.assertRaisesRegex(ValueError, "calibration_dataset_id"):
            CalibrationProfile(profile_id="station_a", status=CALIBRATED)

    def test_validated_profile_requires_independent_validation_dataset(self) -> None:
        with self.assertRaisesRegex(ValueError, "validation_dataset_id"):
            CalibrationProfile(
                profile_id="station_a",
                status=VALIDATED,
                calibration_dataset_id="station_a_train",
            )
        with self.assertRaisesRegex(ValueError, "must be independent"):
            CalibrationProfile(
                profile_id="station_a",
                status=VALIDATED,
                calibration_dataset_id="station_a_all",
                validation_dataset_id="station_a_all",
            )

    def test_validated_profile_is_research_ready(self) -> None:
        profile = CalibrationProfile(
            profile_id="station_a_v1",
            status=VALIDATED,
            calibration_dataset_id="station_a_day_1",
            validation_dataset_id="station_a_day_2",
        )

        self.assertTrue(profile.research_ready)


if __name__ == "__main__":
    unittest.main()
