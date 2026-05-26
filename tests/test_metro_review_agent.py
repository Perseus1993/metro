from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import run_metro_review_agent as review


class MetroReviewAgentTests(unittest.TestCase):
    def test_flags_core_visual_demo_import_and_silent_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            core = root / "sandbox" / "metro_station_sandbox" / "core.py"
            core.parent.mkdir(parents=True)
            core.write_text(
                "\n".join(
                    [
                        "def load():",
                        "    from .visual_demo.geometry import load_station_geometry",
                        "    try:",
                        "        return load_station_geometry()",
                        "    except Exception:",
                        "        return None",
                    ]
                ),
                encoding="utf-8",
            )

            sources = review.collect_python_sources([core], root=root)
            findings = review.review_sources(sources)
            rules = {finding.rule_id for finding in findings}

            self.assertIn("core_imports_visual_demo", rules)
            self.assertIn("broad_exception", rules)
            self.assertTrue(any(finding.severity == "high" for finding in findings))

    def test_detects_duplicate_function_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "scripts" / "dup.py"
            source.parent.mkdir(parents=True)
            body = "\n".join(
                [
                    "def one(value):",
                    "    total = 0",
                    "    for item in value:",
                    "        total += item",
                    "    if total > 10:",
                    "        return total",
                    "    if total == 0:",
                    "        return 0",
                    "    return total + 1",
                    "",
                    "def two(value):",
                    "    total = 0",
                    "    for item in value:",
                    "        total += item",
                    "    if total > 10:",
                    "        return total",
                    "    if total == 0:",
                    "        return 0",
                    "    return total + 1",
                ]
            )
            source.write_text(body, encoding="utf-8")

            findings = review.review_sources(review.collect_python_sources([source], root=root))

            self.assertIn("duplicate_function_body", {finding.rule_id for finding in findings})

    def test_write_outputs_includes_summary(self) -> None:
        args = review.build_parser().parse_args(["--fail-on", "none"])
        finding = review.Finding(
            rule_id="unit",
            severity="high",
            category="coupling",
            path="sandbox/metro_station_sandbox/core.py",
            line=1,
            symbol="unit",
            message="unit",
            recommendation="unit",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = review.OutputPaths(
                csv_path=Path(tmp_dir) / "out.csv",
                json_path=Path(tmp_dir) / "out.json",
                markdown_path=Path(tmp_dir) / "out.md",
            )
            review.write_outputs(paths, args=args, sources=[], findings=[finding])

            payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, payload["summary"]["findings"])
            self.assertIn("Metro Review Agent", paths.markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
