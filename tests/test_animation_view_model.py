from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest

from metro_station_visualizer.config import ASSET_DIR, ROOT


VIEW_MODEL_JS = ASSET_DIR / "animation_view_model.js"
ANIMATION_HTML = ROOT / "animation_demo.html"


@unittest.skipIf(shutil.which("node") is None, "node is required for JS view model checks")
class AnimationViewModelTests(unittest.TestCase):
    def test_view_model_prefers_visual_bundle_and_truth_trace(self) -> None:
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const {{ buildAnimationViewModel, interpolateHeading }} = require({json.dumps(str(VIEW_MODEL_JS))});
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
                terminal_events: [{{ event: "reached_safe_zone", time_seconds: 12, persons: 2 }}],
                aggregate_metrics: {{}},
              }},
              derived: {{
                clearance_audit: {{ completed_agents: 2, remaining_agents: 0, total_agents: 2 }},
                evacuation_metrics: {{ evacuated_persons: 2, clearance_time_seconds: 12 }},
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
              replay_package: {{
                schema_version: "replay_package.v2",
                source_run_id: "run-1",
                station_scene: {{ schema_version: "station_scene.v1", entities: [] }},
                asset_manifest: {{ schema_version: "asset_manifest.v1", assets: [] }},
              }},
            }};

            const view = buildAnimationViewModel(payload);
            assert.equal(view.sourceRunId, "run-1");
            assert.deepEqual(view.agents, [{{ id: 2, visual: true }}]);
            assert.deepEqual(view.queueSamples, [{{ time: 5, derived: true }}]);
            assert.equal(view.clearanceAudit.completed_agents, 2);
            assert.equal(view.elevatorEvents[0].id, 3);
            assert.equal(view.conveyorEvents[0].id, 4);
            assert.equal(view.terminalEvents[0].event, "reached_safe_zone");
            assert.equal(view.evacuationMetrics.evacuated_persons, 2);
            assert.equal(view.replayPackage.schema_version, "replay_package.v2");
            assert.equal(view.stationScene.schema_version, "station_scene.v1");
            assert.equal(view.assetManifest.schema_version, "asset_manifest.v1");

            const traceOnly = buildAnimationViewModel({{
              simulation_trace: payload.simulation_trace,
              visualization_bundle: {{ visual_tracks: [] }},
            }});
            assert.equal(traceOnly.duration, 20);
            assert.equal(traceOnly.clearanceAudit.source, "simulation_trace");
            assert.equal(traceOnly.clearanceAudit.cleared, true);

            const degrees = (value) => value * Math.PI / 180;
            const midpoint = interpolateHeading(degrees(179), degrees(-179), 0.5);
            assert.ok(Math.abs(Math.abs(midpoint) - Math.PI) < 1e-9);
            """
        )

        subprocess.run(["node", "-e", script], check=True, cwd=ROOT)

    def test_animation_demo_uses_view_model_boundary(self) -> None:
        html = ANIMATION_HTML.read_text(encoding="utf-8")

        self.assertIn("assets/animation_view_model.js", html)
        self.assertIn("assets/scene_render_model.js", html)
        self.assertIn('id="sceneLevels"', html)
        self.assertIn("buildAnimationViewModel(TRACK_DATA)", html)
        self.assertIn("const SIM_TRACE = VIEW_MODEL?.simulationTrace", html)
        self.assertIn("const VISUAL_BUNDLE = VIEW_MODEL?.visualizationBundle", html)
        self.assertIn("const STATION_SCENE = VIEW_MODEL?.stationScene", html)
        self.assertIn("SCENE_ELEVATOR_ENTITIES.filter(sceneEntityVisible)", html)
        self.assertIn("renderSceneLevelSummary()", html)
        self.assertIn("drawStationSceneTransportFlows(t)", html)
        self.assertIn("const AGENTS = Array.isArray(VIEW_MODEL?.agents)", html)
        self.assertIn("interpolateHeading?.(a[3], b[3], p)", html)
        self.assertIn("const points = agent.points;", html)
        self.assertNotIn("? agent.presentation_points", html)
        self.assertIn('const IS_EVACUATION = SCENARIO.scenario_mode === "evacuation"', html)
        self.assertIn('event?.event === "reached_safe_zone"', html)
        self.assertIn("if (SHOW_TRAIN_SERVICE) drawTrains(localTime)", html)
        self.assertIn('clearanceTitleEl.textContent = "当前疏散"', html)


if __name__ == "__main__":
    unittest.main()
