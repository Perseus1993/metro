from __future__ import annotations

import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from zipfile import ZipFile

from playwright.sync_api import Page, expect, sync_playwright

from metro_station_designer.server import DesignInspectorHandler, ROOT


def test_browser_runs_exports_imports_and_reruns_paired_algorithm_template(
    tmp_path: Path,
) -> None:
    handler = partial(DesignInspectorHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/inspector.html"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            _create_compact_station(page)
            _configure_required_flows(page)
            _configure_algorithm_template(page)

            with page.expect_response(
                lambda response: response.url.endswith("/api/analysis-cases/baseline")
            ) as baseline_response:
                page.get_by_test_id("save-baseline").click()
            response = baseline_response.value
            assert response.ok, response.json()
            expect(page.get_by_test_id("algorithm-config")).to_be_visible()
            page.get_by_test_id("algorithm-candidate-parameters").fill('{"cost_multiplier": 1.5}')
            page.get_by_test_id("algorithm-preflight").click()
            expect(page.get_by_test_id("algorithm-preflight-status")).to_contain_text(
                "2/2 算法兼容"
            )
            expect(page.get_by_test_id("run-comparison")).to_be_enabled()
            page.get_by_test_id("run-comparison").click()
            expect(page.get_by_test_id("comparison-report")).to_be_visible(timeout=90_000)
            expect(page.get_by_test_id("algorithm-execution-summary")).to_contain_text(
                "metro.shortest_path"
            )
            expect(page.get_by_test_id("algorithm-execution-summary")).to_contain_text(
                "example.dijkstra"
            )
            expect(page.get_by_test_id("comparison-report")).to_contain_text("路由计算耗时")

            with page.expect_download() as download:
                page.get_by_test_id("export-report").click()
            bundle_path = tmp_path / "algorithm-comparison.zip"
            download.value.save_as(bundle_path)
            with ZipFile(bundle_path) as archive:
                assert {
                    "analysis-case.json",
                    "baseline.analysis-case.json",
                    "candidate.analysis-case.json",
                    "comparison-report.json",
                    "decision-report.html",
                    "experiment-plan.json",
                } == set(archive.namelist())
                report = json.loads(archive.read("comparison-report.json"))
                plan = json.loads(archive.read("experiment-plan.json"))
                errors = [run.get("error") for run in report["runs"] if run.get("error")]
                assert not errors, errors
                assert len(report["runs"]) == 6
                assert plan["algorithms"][1]["parameters"] == {"cost_multiplier": 1.5}
                assert report["aggregate"]["template_check"]["complete"] is True
                assert report["aggregate"]["algorithm_execution"]["candidate"]["failure_rate"] == 0
                assert all(run["routing_decision_logs"] for run in report["runs"])
                for seed in (7, 42, 99):
                    fingerprints = {
                        run["paired_input_fingerprint"]
                        for run in report["runs"]
                        if run["seed"] == seed
                    }
                    assert len(fingerprints) == 1
                imported_path = tmp_path / "experiment-plan.json"
                imported_path.write_bytes(archive.read("experiment-plan.json"))
                assert (
                    plan["analysis_case"]["semantic_fingerprint"]
                    == report["spec"]["baseline"]["semantic_fingerprint"]
                )
            expect(page.get_by_test_id("comparison-report")).to_contain_text("失败 0.0%")

            page.reload(wait_until="domcontentloaded", timeout=60_000)
            _create_compact_station(page)
            _configure_required_flows(page)
            page.get_by_test_id("import-experiment-plan").set_input_files(imported_path)
            expect(page.get_by_test_id("algorithm-config")).to_be_visible()
            expect(page.get_by_test_id("control-measure-water_barrier")).to_be_visible()
            expect(page.get_by_test_id("algorithm-candidate-parameters")).to_have_value(
                '{\n  "cost_multiplier": 1.5\n}'
            )
            page.get_by_test_id("algorithm-preflight").click()
            expect(page.get_by_test_id("algorithm-preflight-status")).to_contain_text(
                "2/2 算法兼容"
            )
            page.get_by_test_id("run-comparison").click()
            expect(page.get_by_test_id("comparison-report")).to_be_visible(timeout=90_000)
            expect(page.get_by_test_id("algorithm-execution-summary")).to_contain_text("决策日志")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def _create_compact_station(page: Page) -> None:
    expect(page.get_by_test_id("station-setup-wizard")).to_be_visible()
    page.get_by_test_id("station-preset-compact_single").click()
    expect(page.get_by_test_id("station-setup-wizard")).to_be_hidden(timeout=15_000)
    page.get_by_test_id("generate-station").click()
    expect(page.get_by_test_id("generate-station")).to_be_enabled(timeout=15_000)


def _configure_algorithm_template(page: Page) -> None:
    page.get_by_test_id("load-algorithm-template").click()
    page.get_by_test_id("experiment-horizonMinutes").fill("4")
    page.get_by_test_id("experiment-tickSeconds").fill("10")
    page.get_by_test_id("experiment-initialPlatformPersons").fill("1")
    page.get_by_test_id("control-add-water_barrier").click()
    page.get_by_test_id("control-add-access_closure").click()
    page.get_by_test_id("control-add-staff_guidance").click()
    page.get_by_test_id("control-geometry-x_m").fill("5")
    page.get_by_test_id("control-geometry-y_m").fill("5")
    page.get_by_test_id("control-measure-access_closure").locator("select").select_option(index=3)
    page.get_by_test_id("control-measure-staff_guidance").locator("select").select_option(index=2)
    page.get_by_test_id("control-start-water_barrier").fill("60")
    page.get_by_test_id("control-end-water_barrier").fill("90")
    page.get_by_test_id("control-start-access_closure").fill("120")
    page.get_by_test_id("control-end-access_closure").fill("150")
    page.get_by_test_id("control-start-staff_guidance").fill("180")
    page.get_by_test_id("control-end-staff_guidance").fill("210")
    expect(page.get_by_test_id("control-plan-valid")).to_be_visible()


def _configure_required_flows(page: Page) -> None:
    page.get_by_test_id("palette-flow-entry_flow").click()
    page.get_by_test_id("palette-flow-exit_flow").click()
    page.get_by_test_id("operation-entry_count_hour").fill("120")
    page.get_by_test_id("operation-exit_count_hour").fill("60")
    expect(page.get_by_test_id("save-baseline")).to_be_enabled(timeout=15_000)
