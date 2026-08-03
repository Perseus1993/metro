from __future__ import annotations

import json
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

from metro_station_testkit.replay_browser_catalog import (
    REPLAY_BROWSER_GENERATOR_VERSION,
    REPLAY_BROWSER_SCENES,
    REPLAY_BROWSER_VIEWPORTS,
    replay_browser_cases,
)
from metro_station_testkit.replay_browser_scenes import (
    ReplayBrowserScene,
    build_replay_browser_scene,
)
from metro_station_visualizer.config import ASSET_DIR

from .layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)


VISUALIZER_ROOT = ASSET_DIR.parent
OBSERVATION_TIMES = {
    "loaded": (0.0, 0),
    "first_active": (1.0, 1),
    "peak": (2.0, 3),
    "final": (4.0, 0),
}


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def run_replay_browser_acceptance(
    output_dir: Path | None = None,
) -> ExplorationSuiteReport:
    cases = replay_browser_cases()
    scenes = {scene_id: build_replay_browser_scene(scene_id) for scene_id in REPLAY_BROWSER_SCENES}
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="pm028-e5-") as temporary:
        web_root = Path(temporary) / "visualizer"
        _prepare_web_root(web_root, scenes)
        server, worker = _start_server(web_root)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    results = tuple(
                        _run_case(
                            browser,
                            case,
                            scenes[str(case.factors["scene_id"])],
                            int(server.server_address[1]),
                            output_dir,
                        )
                        for case in cases
                    )
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    primary_screenshots = sum(
        bool(result.artifacts.get("screenshot")) for result in results
    )
    checks = {
        "browser_run_count_is_36": len(results) == 36,
        "all_12_scenes_covered": {
            str(result.case.factors["scene_id"]) for result in results
        }
        == set(REPLAY_BROWSER_SCENES),
        "all_3_viewports_covered": {
            (
                int(result.case.factors["viewport_width"]),
                int(result.case.factors["viewport_height"]),
            )
            for result in results
        }
        == set(REPLAY_BROWSER_VIEWPORTS),
        "all_browser_runs_pass": all(result.status == "ok" for result in results),
        "primary_screenshot_count_is_12": output_dir is None or primary_screenshots == 12,
        "external_binary_assets_remain_audit_only": True,
    }
    return ExplorationSuiteReport(
        suite_id="PM028-E5",
        generator_version=REPLAY_BROWSER_GENERATOR_VERSION,
        results=results,
        coverage={
            **catalog_coverage(cases),
            "scenes": list(REPLAY_BROWSER_SCENES),
            "viewports": [list(item) for item in REPLAY_BROWSER_VIEWPORTS],
            "observation_times": {
                name: {"seconds": seconds, "expected_people": people}
                for name, (seconds, people) in OBSERVATION_TIMES.items()
            },
        },
        checks=checks,
        metadata={
            "renderer": "chromium/headless",
            "programmatic_asset_contract": "asset_manifest.v1",
            "external_asset_contract": "AUDIT/not implemented",
        },
    )


def _run_case(
    browser: Browser,
    case,
    scene: ReplayBrowserScene,
    port: int,
    output_dir: Path | None,
) -> ExplorationCaseResult:
    width = int(case.factors["viewport_width"])
    height = int(case.factors["viewport_height"])
    page = browser.new_page(viewport={"width": width, "height": height})
    page_errors: list[str] = []
    console_errors: list[str] = []
    response_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "response",
        lambda response: response_errors.append(f"{response.status} {response.url}")
        if response.status >= 400
        else None,
    )
    try:
        started = perf_counter()
        url = (
            f"http://127.0.0.1:{port}/animation_demo.html"
            f"?file=tracks_{scene.scene_id}.js&cachecheck={case.case_id}"
        )
        page.goto(url, wait_until="networkidle", timeout=60_000)
        navigation_ms = (perf_counter() - started) * 1000.0
        page.wait_for_function("window.__METRO_SCENE_DEBUG__?.snapshot", timeout=30_000)
        if page.locator("#play").get_attribute("aria-label") == "暂停":
            page.locator("#play").click()

        initial = _snapshot(page)
        level_checks = _check_level_switching(page, scene)
        time_observations = _observe_times(page)
        final_snapshot = _snapshot(page)
        diagnostics = tuple(
            str(item.get("code", "unknown")) for item in initial.get("diagnostics", ())
        )
        diagnostic_code_set = set(diagnostics)
        expected_diagnostic_set = set(scene.expected_diagnostic_codes)
        bounds_intersect = all(
            _bounds_intersect(item, initial["canvas"]) for item in initial["bounds"]
        )
        entities = initial["entities"]
        entity_ids = [str(item["id"]) for item in entities]
        expected_entity_ids = [
            str(item["entity_id"]) for item in scene.station_scene["entities"]
        ]
        ui_check = _ui_intersects_viewport(page, width, height)
        shape_set = {str(item["shape"]) for item in entities}
        rotation_check = _rotation_placement_check(scene, entities)
        stage_visible = page.locator("#stageStatus").get_attribute("data-visible") == "true"
        stage_text = page.locator("#stageStatus").inner_text()
        canvas_nontransparent = bool(
            page.evaluate(
                """
                () => {
                  const canvas = document.querySelector('#scene');
                  const pixels = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height,
                  ).data;
                  return pixels.some((value, index) => index % 4 === 3 && value > 0);
                }
                """
            )
        )
        checks = {
            "http_resources_succeeded": not response_errors,
            "no_page_errors": not page_errors,
            "no_console_errors": not console_errors,
            "scene_model_loaded": initial["entityCount"] > 0,
            "scene_entity_count_matches": initial["entityCount"]
            == len(scene.station_scene["entities"]),
            "scene_entity_ids_are_unique_and_complete": len(entity_ids) == len(set(entity_ids))
            and set(entity_ids) == set(expected_entity_ids),
            "runtime_bindings_have_unique_owners": initial["runtimeBindingCount"]
            == initial["runtimeOwnerCount"],
            "relation_count_matches": initial["relationCount"]
            == len(scene.station_scene["relations"]),
            "elevator_count_is_scene_driven": len(initial["visibleElevatorIds"])
            == scene.expected_elevator_count,
            "diagnostics_match_expectation": diagnostic_code_set == expected_diagnostic_set,
            "diagnostics_are_visible_when_present": (
                bool(expected_diagnostic_set) == stage_visible
                and all(code in stage_text for code in expected_diagnostic_set)
            ),
            "all_entity_bounds_intersect_canvas": bounds_intersect,
            "canvas_has_nontransparent_pixels": canvas_nontransparent,
            "all_levels_switch_exactly": all(level_checks.values()),
            "four_time_observations_match_trace_summary": all(
                observation["observed_people"] == observation["expected_people"]
                for observation in time_observations.values()
            ),
            "viewport_keeps_key_ui_visible": ui_check,
            "mixed_geometry_supported": scene.scene_id != "B11"
            or {"polygon", "polyline", "point"}.issubset(shape_set),
            "rotation_and_placement_supported": rotation_check,
            "final_seek_is_stable": final_snapshot["renderedAtSeconds"] == 4,
        }

        screenshot = _capture_evidence(page, case.case_id, output_dir, checks)
        navigation_entry = page.evaluate(
            """
            () => {
              const item = performance.getEntriesByType('navigation')[0];
              return item ? {
                domContentLoadedMs: item.domContentLoadedEventEnd,
                loadEventMs: item.loadEventEnd,
              } : {};
            }
            """
        )
        stage = ExplorationStageResult(
            stage="real_browser",
            status="ok" if all(checks.values()) else "review",
            diagnostic_codes=diagnostics,
            checks=checks,
            metrics={
                "viewport": [width, height],
                "navigation_wall_ms": round(navigation_ms, 3),
                "dom_content_loaded_ms": navigation_entry.get("domContentLoadedMs"),
                "load_event_ms": navigation_entry.get("loadEventMs"),
                "scene_model_build_ms": initial["sceneModelBuildMs"],
                "first_scene_frame_ms": initial["firstSceneFrameMs"],
                "entity_count": initial["entityCount"],
                "relation_count": initial["relationCount"],
                "runtime_binding_count": initial["runtimeBindingCount"],
                "trajectory_point_count": 5,
                "time_observations": time_observations,
                "level_checks": level_checks,
            },
            error=(
                "; ".join((*page_errors, *console_errors, *response_errors)) or None
            ),
        )
        return ExplorationCaseResult(
            case=case,
            observed_outcome="diagnostic" if diagnostics else "pass",
            stages=(stage,),
            checks=checks,
            artifacts={"screenshot": screenshot} if screenshot else {},
        )
    except Exception as exc:
        screenshot = _capture_failure(page, case.case_id, output_dir)
        return ExplorationCaseResult(
            case=case,
            observed_outcome="error",
            stages=(
                ExplorationStageResult(
                    stage="real_browser",
                    status="review",
                    error=f"{type(exc).__name__}: {exc}",
                ),
            ),
            checks={"execution_completed": False},
            artifacts={"screenshot": screenshot} if screenshot else {},
        )
    finally:
        page.close()


def _check_level_switching(page: Page, scene: ReplayBrowserScene) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    entity_levels = {
        str(item["entity_id"]): {str(level_id) for level_id in item.get("level_ids", ())}
        for item in scene.station_scene["entities"]
    }
    buttons = page.locator("#sceneLevels [data-level-id]")
    checks["level_button_count"] = buttons.count() == scene.expected_level_count
    for index, level in enumerate(scene.station_scene["levels"]):
        level_id = str(level["level_id"])
        button = buttons.nth(index)
        button.click()
        snapshot = _snapshot(page)
        expected = {
            entity_id for entity_id, level_ids in entity_levels.items() if level_id in level_ids
        }
        checks[f"level:{level_id}"] = (
            snapshot["activeLevelId"] == level_id
            and set(snapshot["visibleEntityIds"]) == expected
            and button.get_attribute("aria-pressed") == "true"
        )
        button.click()
    checks["all_levels_restored"] = _snapshot(page)["activeLevelId"] is None
    return checks


def _observe_times(page: Page) -> dict[str, dict[str, float | int]]:
    observations: dict[str, dict[str, float | int]] = {}
    for name, (seconds, expected_people) in OBSERVATION_TIMES.items():
        page.evaluate("seconds => window.demoJumpTo(seconds)", seconds)
        snapshot = _snapshot(page)
        observations[name] = {
            "seconds": seconds,
            "expected_people": expected_people,
            "observed_people": int(snapshot["peopleCount"]),
        }
    return observations


def _snapshot(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__METRO_SCENE_DEBUG__.snapshot()")


def _bounds_intersect(bounds: dict[str, Any], canvas: dict[str, Any]) -> bool:
    return (
        float(bounds["x"]) < float(canvas["width"])
        and float(bounds["y"]) < float(canvas["height"])
        and float(bounds["x"]) + float(bounds["w"]) > 0
        and float(bounds["y"]) + float(bounds["h"]) > 0
    )


def _ui_intersects_viewport(page: Page, width: int, height: int) -> bool:
    selectors = ("#scene", "#sceneLevels", "#peopleCount")
    for selector in selectors:
        box = page.locator(selector).bounding_box()
        if box is None:
            return False
        if box["x"] >= width or box["y"] >= height:
            return False
        if box["x"] + box["width"] <= 0 or box["y"] + box["height"] <= 0:
            return False
    return True


def _rotation_placement_check(
    scene: ReplayBrowserScene,
    entities: list[dict[str, Any]],
) -> bool:
    if scene.scene_id != "B12":
        return True
    entity = next(item for item in entities if item["id"] == scene.rotated_entity_id)
    return (
        float(entity["rotationDeg"]) == 30.0
        and float(entity["placementRotationDeg"]) == 15.0
        and entity["assetId"] is not None
        and len(entity["points"]) == 4
    )


def _capture_evidence(
    page: Page,
    case_id: str,
    output_dir: Path | None,
    checks: dict[str, bool],
) -> str | None:
    if output_dir is None:
        return None
    is_primary = "-1600x1000" in case_id
    if not is_primary and all(checks.values()):
        return None
    target = output_dir / "screenshots" / f"{case_id}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target), full_page=False)
    return str(target)


def _capture_failure(page: Page, case_id: str, output_dir: Path | None) -> str | None:
    if output_dir is None:
        return None
    target = output_dir / "failures" / case_id / "browser.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(target), full_page=False)
    except Exception:
        return None
    return str(target)


def _prepare_web_root(
    web_root: Path,
    scenes: dict[str, ReplayBrowserScene],
) -> None:
    web_root.mkdir(parents=True)
    shutil.copy2(VISUALIZER_ROOT / "animation_demo.html", web_root)
    shutil.copytree(ASSET_DIR, web_root / "assets")
    for scene_id, scene in scenes.items():
        payload = _browser_payload(scene)
        (web_root / f"tracks_{scene_id}.js").write_text(
            "window.JPS_TRACKS = "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + ";\n",
            encoding="utf-8",
        )


def _start_server(web_root: Path) -> tuple[ThreadingHTTPServer, Thread]:
    handler = partial(_QuietStaticHandler, directory=str(web_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _browser_payload(scene: ReplayBrowserScene) -> dict[str, Any]:
    snapshots = [
        {"time_seconds": seconds, "metrics": {"active_agents": people}}
        for seconds, people in ((0.0, 0), (1.0, 1), (2.0, 3), (4.0, 0))
    ]
    return {
        "schema_version": "visualization_bundle.v1",
        "source_run_id": f"pm028-e5-{scene.scene_id}",
        "duration": 4.0,
        "demo_window_seconds": 4.0,
        "scenario": {
            "station_name": f"PM-028 E5 {scene.scene_id}",
            "hour": 18,
            "entry_count_hour": 0,
            "exit_count_hour": 0,
            "source_label": "pm028_e5_browser",
        },
        "agents": [
            {
                "id": 1,
                "n": 1,
                "points": [
                    [1.0, 240.0, 250.0, 0.0, 1.0, None, None, None, "target"],
                    [2.0, 300.0, 260.0, 0.0, 1.0, None, None, None, "target"],
                    [3.0, 360.0, 270.0, 0.0, 0.0, None, None, None, "target"],
                ],
            },
            {
                "id": 2,
                "n": 2,
                "points": [
                    [2.0, 420.0, 300.0, 0.0, 1.0, None, None, None, "queue"],
                    [4.0, 520.0, 320.0, 0.0, 0.0, None, None, None, "target"],
                ],
            },
        ],
        "simulation_trace": {
            "schema_version": "simulation_trace.v1",
            "run_id": f"pm028-e5-{scene.scene_id}",
            "metadata": {"scenario": {"station_name": f"PM-028 E5 {scene.scene_id}"}},
            "snapshots": snapshots,
            "terminal_events": [],
        },
        "visualization_bundle": {
            "schema_version": "visualization_bundle.v1",
            "source_run_id": f"pm028-e5-{scene.scene_id}",
        },
        "replay_package": {
            "schema_version": "replay_package.v2",
            "source_run_id": f"pm028-e5-{scene.scene_id}",
            "station_scene": scene.station_scene,
            "asset_manifest": scene.asset_manifest,
            "simulation_trace_ref": "#/simulation_trace",
            "visualization_bundle_ref": "#/visualization_bundle",
        },
        "clearance_audit": {"cleared": False, "total_agents": 3},
    }

