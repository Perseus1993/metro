from __future__ import annotations

import json
import tempfile
import unittest

from scripts import run_metro_boundary_hack_agent as hack


class MetroBoundaryHackAgentTests(unittest.TestCase):
    def test_limit_cases_keeps_mixed_intents_and_origin_kinds(self) -> None:
        cases = [
            hack.BoundaryCase(
                f"case_{index:04d}",
                f"{origin}:x:{index}",
                level,
                (float(index), float(index)),
                intent,
                expected,
            )
            for index, (origin, level, intent, expected) in enumerate(
                [
                    ("node", "b1_concourse", "enter_and_board", "boarded"),
                    ("node", "b1_concourse", "enter_and_board", "boarded"),
                    ("facility", "b1_concourse", "enter_and_board", "boarded"),
                    ("platform_waiting_slot", "b2_platform", "exit_station", "exited"),
                    ("platform_waiting_slot", "b2_platform", "transfer", "boarded"),
                    ("boundary", "b2_platform", "exit_station", "exited"),
                ],
                start=1,
            )
        ]

        limited = hack._limit_cases(cases, 4)

        self.assertEqual(4, len(limited))
        self.assertIn("enter_and_board", {case.intent for case in limited})
        self.assertIn("exit_station", {case.intent for case in limited})

    def test_run_single_platform_exit_case_departs(self) -> None:
        args = hack.build_parser().parse_args(
            [
                "--minutes",
                "8",
                "--max-cases",
                "1",
                "--initial-train-offset-seconds",
                "10",
                "--train-headway-seconds",
                "60",
                "--train-dwell-seconds",
                "30",
            ]
        )
        model = hack.MetroStationModel(hack.make_scenario(args), seed=7)
        point = model.layout_graph.platform_waiting_position(0)
        case = hack.BoundaryCase(
            "unit_platform_exit",
            "platform_waiting_slot:0",
            "b2_platform",
            point,
            "exit_station",
            "exited",
        )

        row = hack.run_case(case, args, seed=8)

        self.assertEqual("ok", row["status"], row)
        self.assertEqual("departed", row["final_state"])
        self.assertEqual(0, row["boarded_persons"])

    def test_write_outputs_includes_reward_summary(self) -> None:
        args = hack.build_parser().parse_args(["--max-cases", "1"])
        case = hack.BoundaryCase(
            "case_0001",
            "node:test",
            "b1_concourse",
            (1.0, 2.0),
            "enter_and_board",
            "boarded",
        )
        row = {field: "" for field in hack.FIELDNAMES}
        row.update(
            {
                "case_id": case.case_id,
                "status": "failed",
                "severity": "hard_failure",
                "reward_points": 100,
                "intent": case.intent,
                "expected_outcome": case.expected_outcome,
                "origin": case.origin,
                "level_id": case.level_id,
                "start_x": 1.0,
                "start_y": 2.0,
                "seconds_run": 60,
                "failure_reason": "unit",
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = hack.OutputPaths(
                csv_path=hack.Path(tmp_dir) / "out.csv",
                json_path=hack.Path(tmp_dir) / "out.json",
                markdown_path=hack.Path(tmp_dir) / "out.md",
            )

            hack.write_outputs(paths, args=args, cases=[case], rows=[row])

            payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(100, payload["summary"]["reward_points"])
            self.assertIn("Hans Landa", paths.markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
