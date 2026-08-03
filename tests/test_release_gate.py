from __future__ import annotations

import unittest

from metro_station_experiments.release_gate import assess_release


class ReleaseGateTests(unittest.TestCase):
    def test_all_evidence_passes(self) -> None:
        report = assess_release(
            emergency={"summary": {"runs": 3, "errors": 0, "acceptance_failed": 0}},
            reliability_reports=[
                {
                    "groups": [
                        {
                            "population": population,
                            "sample_count": 30,
                            "execution_failures": 0,
                            "acceptance_failures": 0,
                        }
                        for population in (60, 120, 240)
                    ]
                }
            ],
            sensitivity={"status": "pass"},
            performance={"status": "pass"},
            calibration={"status": "pass"},
            density_threshold_authority_approved=True,
        )

        self.assertEqual("pass", report["status"])
        self.assertTrue(report["production_ready"])

    def test_collects_material_blockers(self) -> None:
        report = assess_release(
            emergency={"summary": {"runs": 3, "errors": 0, "acceptance_failed": 0}},
            reliability_reports=[
                {
                    "groups": [
                        {
                            "population": 60,
                            "sample_count": 30,
                            "execution_failures": 0,
                            "acceptance_failures": 0,
                        }
                    ]
                }
            ],
            sensitivity={"status": "fail", "inert_parameters": [{"code": "inert"}]},
            performance={"status": "fail", "issues": [{"code": "slow"}]},
            calibration={"status": "blocked", "issues": [{"code": "missing"}]},
        )

        self.assertEqual("blocked", report["status"])
        codes = {item["code"] for item in report["blockers"]}
        self.assertTrue(
            {
                "reliability.insufficient_samples",
                "inert",
                "slow",
                "missing",
                "safety.density_threshold_not_approved",
            }.issubset(codes)
        )

    def test_stale_reliability_evidence_is_not_counted(self) -> None:
        report = assess_release(
            emergency={
                "metadata": {"model_evidence_version": "v2"},
                "summary": {"runs": 1, "errors": 0, "acceptance_failed": 0},
            },
            reliability_reports=[
                {
                    "model_evidence_version": "v1",
                    "groups": [
                        {
                            "population": 60,
                            "sample_count": 30,
                            "execution_failures": 0,
                            "acceptance_failures": 0,
                        }
                    ],
                }
            ],
            sensitivity={"model_evidence_version": "v2", "status": "pass"},
            performance={"model_evidence_version": "v2", "status": "pass"},
            calibration={"status": "pass"},
            required_populations=(60,),
            density_threshold_authority_approved=True,
            expected_model_evidence_version="v2",
        )

        self.assertEqual("blocked", report["status"])
        self.assertIn(
            "evidence.model_version_mismatch",
            {item["code"] for item in report["blockers"]},
        )
        reliability = [
            check
            for check in report["checks"]
            if check["component"] == "reliability" and "population" in check
        ]
        self.assertEqual(0, reliability[0]["sample_count"])


if __name__ == "__main__":
    unittest.main()
