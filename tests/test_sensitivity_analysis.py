from __future__ import annotations

import unittest

from metro_station_experiments.sensitivity import sensitivity_report


class SensitivityAnalysisTests(unittest.TestCase):
    def test_report_ranks_parameter_by_relative_metric_span(self) -> None:
        rows = []
        for parameter, values in {
            "walk": [(1, 120), (2, 100), (3, 80)],
            "gate": [(1, 101), (2, 100), (3, 99)],
        }.items():
            for value, clearance in values:
                rows.append(
                    {
                        "sensitivity_parameter": parameter,
                        "sensitivity_value": value,
                        "sensitivity_baseline": value == 2,
                        "status": "ok",
                        "acceptance_status": "pass",
                        "clearance_time_seconds": clearance,
                        "peak_local_density_persons_m2": 4,
                    }
                )

        report = sensitivity_report(rows)

        self.assertEqual("pass", report["status"])
        self.assertEqual("walk", report["ranking"][0]["parameter"])
        self.assertEqual(0.4, report["ranking"][0]["max_relative_span"])

    def test_failed_variant_fails_report(self) -> None:
        rows = [
            {
                "sensitivity_parameter": "walk",
                "sensitivity_value": value,
                "sensitivity_baseline": value == 2,
                "status": "ok",
                "acceptance_status": "fail" if value == 1 else "pass",
                "clearance_time_seconds": 100,
                "peak_local_density_persons_m2": 4,
            }
            for value in (1, 2, 3)
        ]

        self.assertEqual("fail", sensitivity_report(rows)["status"])

    def test_parameter_without_observable_effect_fails_report(self) -> None:
        rows = [
            {
                "sensitivity_parameter": "gate",
                "sensitivity_value": value,
                "sensitivity_baseline": value == 55,
                "status": "ok",
                "acceptance_status": "pass",
                "clearance_time_seconds": 240,
                "peak_local_density_persons_m2": 3.2,
            }
            for value in (44, 55, 66)
        ]

        report = sensitivity_report(rows)

        self.assertEqual("fail", report["status"])
        self.assertEqual("sensitivity.no_observable_effect", report["inert_parameters"][0]["issue"])

    def test_exactly_one_baseline_is_required(self) -> None:
        rows = [
            {
                "sensitivity_parameter": "walk",
                "sensitivity_value": 1,
                "sensitivity_baseline": False,
            }
        ]

        with self.assertRaisesRegex(ValueError, "exactly one baseline"):
            sensitivity_report(rows)


if __name__ == "__main__":
    unittest.main()
