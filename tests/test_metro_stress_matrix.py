from __future__ import annotations

import json
import tempfile
import unittest

from scripts import run_metro_stress_matrix as stress


class MetroStressMatrixTests(unittest.TestCase):
    def test_parse_lists_and_explicit_pairs(self) -> None:
        self.assertEqual((60, 120, 240), stress.parse_int_list("60,120,240"))
        self.assertEqual(((60, 30), (120, 90)), stress.parse_pairs("60:30,120:90"))

    def test_build_cases_crosses_flows_and_seeds(self) -> None:
        cases = stress.build_cases(
            entries=(60, 120),
            exits=(30,),
            seeds=(1, 2),
            pairs=None,
        )

        self.assertEqual(
            [
                stress.StressCase(60, 30, 1),
                stress.StressCase(60, 30, 2),
                stress.StressCase(120, 30, 1),
                stress.StressCase(120, 30, 2),
            ],
            cases,
        )

    def test_summarize_run_uses_final_and_max_frame_metrics(self) -> None:
        args = stress.build_parser().parse_args(
            [
                "--minutes",
                "2",
                "--entries",
                "60",
                "--exits",
                "60",
                "--design-template",
                "single_level_terminal",
            ]
        )
        case = stress.StressCase(entry_count_hour=60, exit_count_hour=60, seed=7)
        frames = [
            {
                "metrics": {
                    "station_persons": 1,
                    "gate_queue_persons": 0,
                    "vertical_queue_persons": 0,
                    "door_queue_persons": 0,
                    "platform_waiting_persons": 0,
                    "crowding_index": 0.2,
                    "average_walk_speed_factor": 1.0,
                }
            },
            {
                "metrics": {
                    "station_persons": 3,
                    "gate_queue_persons": 2,
                    "vertical_queue_persons": 1,
                    "door_queue_persons": 4,
                    "platform_waiting_persons": 5,
                    "spawned_persons": 4,
                    "spawned_entry_persons": 2,
                    "spawned_exit_persons": 2,
                    "boarded_persons": 1,
                    "exit_gate_served_persons": 1,
                    "average_system_minutes": 0.5,
                    "crowding_index": 1.4,
                    "average_walk_speed_factor": 0.75,
                    "movement_backend": "FakeBackend",
                    "jupedsim_operational_model": "social_force",
                    "jupedsim_steps": 12,
                    "jupedsim_batches": 3,
                    "audit_counts": {"debug": 2},
                }
            },
        ]

        row = stress.summarize_run(args=args, case=case, frames=frames, elapsed_seconds=0.12345)

        self.assertEqual("ok", row["status"])
        self.assertEqual("entry_60_exit_60_seed_7", row["run_id"])
        self.assertEqual(2, row["completed_persons"])
        self.assertEqual(0.5, row["completion_rate"])
        self.assertEqual(3, row["station_persons_max"])
        self.assertEqual(4, row["door_queue_persons_max"])
        self.assertEqual(0.75, row["average_walk_speed_factor_min"])
        self.assertEqual("FakeBackend", row["movement_backend"])
        self.assertEqual("social_force", row["jupedsim_operational_model"])

    def test_write_outputs_creates_csv_json_and_markdown(self) -> None:
        args = stress.build_parser().parse_args(["--entries", "60", "--exits", "60"])
        case = stress.StressCase(entry_count_hour=60, exit_count_hour=60, seed=42)
        row = {field: None for field in stress.FIELDNAMES}
        row.update(
            {
                "run_id": case.run_id,
                "status": "ok",
                "entry_count_hour": 60,
                "exit_count_hour": 60,
                "seed": 42,
                "spawned_persons": 2,
                "completed_persons": 1,
                "station_persons_final": 1,
                "station_persons_max": 2,
                "audit_counts": {"debug": 1},
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = stress.OutputPaths(
                csv_path=stress.Path(tmp_dir) / "matrix.csv",
                json_path=stress.Path(tmp_dir) / "matrix.json",
                markdown_path=stress.Path(tmp_dir) / "matrix.md",
            )

            stress.write_outputs(paths, args=args, cases=[case], rows=[row])

            self.assertIn("entry_count_hour", paths.csv_path.read_text(encoding="utf-8"))
            json_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, json_payload["summary"]["ok"])
            self.assertEqual(case.run_id, json_payload["runs"][0]["run_id"])
            markdown_text = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Metro Stress Matrix Summary", markdown_text)
            self.assertIn(case.run_id, paths.csv_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
