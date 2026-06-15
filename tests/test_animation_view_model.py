from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW_MODEL_JS = (
    ROOT
    / "sandbox"
    / "metro_station_sandbox"
    / "visual_demo"
    / "assets"
    / "animation_view_model.js"
)
ANIMATION_HTML = (
    ROOT
    / "sandbox"
    / "metro_station_sandbox"
    / "visual_demo"
    / "animation_demo.html"
)


@unittest.skipIf(shutil.which("node") is None, "node is required for JS view model checks")
class AnimationViewModelTests(unittest.TestCase):
    def test_view_model_prefers_visual_bundle_and_truth_trace(self) -> None:
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const {{ buildAnimationViewModel }} = require({json.dumps(str(VIEW_MODEL_JS))});
            const payload = {{
              duration: 10,
              agents: [{{ id: 1, legacy: true }}],
              clearance_audit: {{ completed_agents: 0, remaining_agents: 1, total_agents: 1 }},
              queue_samples: [{{ time: 0, legacy: true }}],
              simulation_trace: {{
                metadata: {{ scenario: {{ station_name: "trace_station" }} }},
                snapshots: [
                  {{ time_seconds: 0, passengers: [{{ id: 1 }}], metrics: {{}} }},
                  {{
                    time_seconds: 20,
                    passengers: [],
                    metrics: {{
                      spawned_persons: 2,
                      boarded_persons: 2,
                      exit_gate_served_persons: 0,
                      station_persons: 0,
                    }},
                  }},
                ],
                facility_events: [],
                aggregate_metrics: {{}},
              }},
              derived: {{
                clearance_audit: {{ completed_agents: 2, remaining_agents: 0, total_agents: 2 }},
                queue_samples: [{{ time: 5, derived: true }}],
              }},
              visualization_bundle: {{
                source_run_id: "run-1",
                visual_tracks: [{{ id: 2, visual: true }}],
                visual_facility_animations: {{
                  elevator_events: [{{ id: 3, start: 1, board_end: 2, arrive: 3, end: 4 }}],
                  conveyor_events: [{{ id: 4, start: 1, end: 4, line: [[0,0],[1,1]] }}],
                }},
              }},
            }};

            const view = buildAnimationViewModel(payload);
            assert.equal(view.sourceRunId, "run-1");
            assert.deepEqual(view.agents, [{{ id: 2, visual: true }}]);
            assert.deepEqual(view.queueSamples, [{{ time: 5, derived: true }}]);
            assert.equal(view.clearanceAudit.completed_agents, 2);
            assert.equal(view.elevatorEvents[0].id, 3);
            assert.equal(view.conveyorEvents[0].id, 4);

            const traceOnly = buildAnimationViewModel({{
              simulation_trace: payload.simulation_trace,
              visualization_bundle: {{ visual_tracks: [] }},
            }});
            assert.equal(traceOnly.duration, 20);
            assert.equal(traceOnly.clearanceAudit.source, "simulation_trace");
            assert.equal(traceOnly.clearanceAudit.cleared, true);
            """
        )

        subprocess.run(["node", "-e", script], check=True, cwd=ROOT)

    def test_animation_demo_uses_view_model_boundary(self) -> None:
        html = ANIMATION_HTML.read_text(encoding="utf-8")

        self.assertIn("assets/animation_view_model.js", html)
        self.assertIn("buildAnimationViewModel(TRACK_DATA)", html)
        self.assertIn("const SIM_TRACE = VIEW_MODEL?.simulationTrace", html)
        self.assertIn("const VISUAL_BUNDLE = VIEW_MODEL?.visualizationBundle", html)
        self.assertIn("const AGENTS = Array.isArray(VIEW_MODEL?.agents)", html)


if __name__ == "__main__":
    unittest.main()
