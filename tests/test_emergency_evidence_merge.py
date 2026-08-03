from __future__ import annotations

import unittest

from metro_station_experiments.evidence_merge import (
    merge_emergency_evidence,
)


def payload(seed: int, *, version: str = "v1"):
    return {
        "metadata": {
            "model_evidence_version": version,
            "configuration_fingerprint": "same",
        },
        "runs": [
            {
                "run_id": f"run_{seed}",
                "initial_persons": 120,
                "seed": seed,
                "status": "ok",
                "acceptance_status": "pass",
            }
        ],
    }


class EmergencyEvidenceMergeTests(unittest.TestCase):
    def test_merges_compatible_unique_rows(self) -> None:
        merged = merge_emergency_evidence([payload(2), payload(1)])

        self.assertEqual(2, merged["summary"]["runs"])
        self.assertEqual([1, 2], [row["seed"] for row in merged["runs"]])

    def test_rejects_mixed_versions_and_duplicate_runs(self) -> None:
        with self.assertRaisesRegex(ValueError, "versions"):
            merge_emergency_evidence([payload(1), payload(2, version="v2")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            merge_emergency_evidence([payload(1), payload(1)])


if __name__ == "__main__":
    unittest.main()
