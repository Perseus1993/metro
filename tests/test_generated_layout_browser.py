from __future__ import annotations

import json
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout
from metro_station_visualizer.config import ASSET_DIR


VISUALIZER_ROOT = ASSET_DIR.parent


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def test_generated_three_level_layout_renders_in_real_browser(tmp_path: Path) -> None:
    design = generate_layout(_browser_recipe())
    scenario = _scenario(design)
    layout = DesignCompiler.compile(design, scenario)
    scene = compile_station_scene(scenario, layout.facilities)
    manifest = compile_procedural_asset_manifest(scene)
    web_root = tmp_path / "visualizer"
    web_root.mkdir()
    shutil.copy2(VISUALIZER_ROOT / "animation_demo.html", web_root)
    shutil.copytree(ASSET_DIR, web_root / "assets")
    payload = _browser_payload(scene.as_dict(), manifest.as_dict())
    (web_root / "generated_tracks.js").write_text(
        "window.JPS_TRACKS = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    handler = partial(QuietStaticHandler, directory=str(web_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    page_errors: list[str] = []
    console_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )
            url = (
                f"http://127.0.0.1:{server.server_address[1]}/animation_demo.html"
                "?file=generated_tracks.js&cachecheck=generated-layout-browser"
            )
            page.goto(url, wait_until="networkidle", timeout=60_000)
            levels = page.locator("#sceneLevels .rail-direction")
            expect(levels).to_have_count(3)
            expect(page.locator("#sceneLevels")).to_contain_text("B1 Concourse")
            expect(page.locator("#sceneLevels")).to_contain_text("B2 Transfer Hall")
            expect(page.locator("#sceneLevels")).to_contain_text("B3 Platform")
            expect(page.locator("#stageStatusTitle")).not_to_contain_text("失败")
            assert page.evaluate(
                """
                () => {
                  const canvas = document.querySelector('#scene');
                  const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
                  return pixels.some((value, index) => index % 4 === 3 && value > 0);
                }
                """
            )
            assert page_errors == []
            assert console_errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def _browser_recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="browser-three-level-six-elevators",
        seed=79,
        archetype="three_level_transfer",
        entrance_count=4,
        gate_count=2,
        elevator_count=6,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=True,
        asset_density="dense",
        geometry_variant=8,
        operation_profile="train_outage",
    )


def _scenario(design: StationDesignDocument) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="generated_layout_browser",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="generated_layout_browser",
        sample_hours=1,
        station_design=design,
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _browser_payload(
    scene: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "visualization_bundle.v1",
        "source_run_id": "generated-layout-browser",
        "duration": 1.0,
        "scenario": {"station_name": "Generated six-elevator station", "hour": 18},
        "agents": [
            {
                "id": 1,
                "n": 1,
                "points": [
                    [0.0, 100.0, 100.0, 0.0, 1.0, None, None, None, "target"],
                    [1.0, 120.0, 100.0, 0.0, 1.0, None, None, None, "target"],
                ],
            }
        ],
        "simulation_trace": {
            "schema_version": "simulation_trace.v1",
            "run_id": "generated-layout-browser",
            "metadata": {"scenario": {"station_name": "Generated six-elevator station"}},
            "snapshots": [],
            "terminal_events": [],
        },
        "visualization_bundle": {
            "schema_version": "visualization_bundle.v1",
            "source_run_id": "generated-layout-browser",
        },
        "replay_package": {
            "schema_version": "replay_package.v2",
            "source_run_id": "generated-layout-browser",
            "station_scene": scene,
            "asset_manifest": manifest,
            "simulation_trace_ref": "#/simulation_trace",
            "visualization_bundle_ref": "#/visualization_bundle",
        },
        "clearance_audit": {"cleared": False, "total_agents": 1},
    }
