from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metro_station_visualizer.config import ROOT as VISUALIZER_ROOT
from scripts.generate_goal_journey_visual import build_visual_payload, main


DEMO = VISUALIZER_ROOT / "goal_journey_graph_demo.html"


class GoalJourneyVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_visual_payload(seed=42)
        cls.crowded = build_visual_payload(seed=42, scenario_id="crowded_full_journey")

    def test_payload_uses_real_single_passenger_probe_frames(self) -> None:
        self.assertEqual("single_passenger_clear_scene", self.payload["mode"])
        self.assertGreater(len(self.payload["frames"]), 150)
        self.assertEqual(21, len(self.payload["traces"]))
        self.assertEqual(
            ["gate", "stairs", "train_door"],
            [event["facility_kind"] for event in self.payload["service_events"]],
        )
        self.assertEqual("departed", self.payload["frames"][-1]["passenger_state"])

    def test_frame_time_and_graph_trace_are_monotonic(self) -> None:
        frame_times = [frame["time_seconds"] for frame in self.payload["frames"]]
        trace_times = [trace["time_seconds"] for trace in self.payload["traces"]]
        self.assertEqual(sorted(frame_times), frame_times)
        self.assertEqual(sorted(trace_times), trace_times)
        self.assertEqual(self.payload["duration_seconds"], frame_times[-1])

    def test_generator_writes_file_safe_javascript(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "journey.js"
            self.assertEqual(0, main(["--output", str(output)]))
            text = output.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.GOAL_JOURNEY_DEMO_DATASETS = "))
            self.assertTrue(text.rstrip().endswith(";"))

    def test_crowded_payload_contains_real_moving_people_and_three_replans(self) -> None:
        self.assertEqual("single_passenger_crowded_scene", self.crowded["mode"])
        self.assertEqual(92, self.crowded["background_crowd_size"])
        self.assertTrue(all(len(frame["crowd"]) >= 92 for frame in self.crowded["frames"]))
        stalls = [
            trace for trace in self.crowded["traces"] if trace["event_kind"] == "progress_stalled"
        ]
        self.assertEqual(3, len(stalls))

    def test_demo_references_generated_data_and_renderers(self) -> None:
        html = DEMO.read_text(encoding="utf-8")
        self.assertIn("goal_journey_demo_data.js", html)
        self.assertIn("goal_journey_crowded_data.js", html)
        self.assertIn("goal_journey_graph_scene.js", html)
        self.assertIn("goal_journey_graph_app.js", html)
        self.assertIn('id="journeyCanvas"', html)
        self.assertIn('id="graphNodes"', html)
        self.assertIn('id="modeSelect"', html)


if __name__ == "__main__":
    unittest.main()
