from __future__ import annotations

import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic
from zipfile import ZipFile

from playwright.sync_api import Page, expect, sync_playwright

from metro_station_designer.server import DesignInspectorHandler, ROOT


def test_browser_completes_water_barrier_comparison_and_reimports_baseline(
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
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            _create_compact_station(page)
            _configure_small_demand(page)
            page.get_by_test_id("experiment-horizonMinutes").fill("4")
            page.get_by_test_id("experiment-tickSeconds").fill("10")
            page.get_by_test_id("control-add-access_closure").click()
            page.get_by_test_id("control-add-access_closure").click()
            expect(page.get_by_test_id("control-measure-access_closure")).to_have_count(2)
            expect(page.get_by_test_id("control-plan-issues")).to_contain_text("同时控制同一设施")
            page.get_by_test_id("control-remove-access_closure").last.click()
            page.get_by_test_id("control-remove-access_closure").click()
            expect(page.get_by_test_id("control-measure-access_closure")).to_have_count(0)
            page.get_by_test_id("control-add-water_barrier").click()
            expect(page.get_by_test_id("control-measure-water_barrier")).to_be_visible()
            page.get_by_test_id("control-start-water_barrier").fill("0")
            page.get_by_test_id("control-end-water_barrier").fill("30")
            expect(page.get_by_test_id("control-plan-valid")).to_be_visible()
            expect(page.get_by_test_id("control-timeline-marker")).to_have_count(2)
            expect(page.get_by_test_id("control-add-isolation_barrier")).to_be_enabled()
            page.get_by_test_id("control-add-isolation_barrier").click()
            expect(page.get_by_test_id("control-measure-isolation_barrier")).to_be_visible()
            page.get_by_test_id("control-remove-isolation_barrier").click()

            page.get_by_test_id("save-baseline").click()
            expect(page.locator(".experiment-case").filter(has_text="基准")).to_be_visible()
            expect(page.locator(".experiment-case").first).to_contain_text("uncalibrated")
            expect(page.locator(".experiment-case").first).to_contain_text(
                "Internal exploration only"
            )
            baseline_fingerprint = page.locator(".experiment-case code").first.text_content()
            with page.expect_download() as baseline_download:
                page.get_by_test_id("export-baseline").click()
            baseline_path = tmp_path / "baseline.analysis-case.json"
            baseline_download.value.save_as(baseline_path)
            exported_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            assert (
                exported_baseline["simulation"]["control_plan"]["schema_version"]
                == "control-plan/v1"
            )
            assert (
                exported_baseline["simulation"]["control_plan"]["measures"][0]["kind"]
                == "water_barrier"
            )

            page.get_by_text("可选设施与障碍物", exact=True).click()
            page.get_by_test_id("palette-component-obstacle").click()
            expect(page.get_by_test_id("save-candidate")).to_be_enabled(timeout=10_000)
            page.get_by_test_id("save-candidate").click()
            expect(page.get_by_test_id("case-differences")).to_contain_text("输入差异 1 项")
            expect(page.get_by_test_id("case-differences")).to_contain_text("design.elements")

            comparison_started = monotonic()
            page.get_by_test_id("run-comparison").click()
            expect(page.get_by_test_id("comparison-report")).to_be_visible(timeout=90_000)
            assert monotonic() - comparison_started < 60
            expect(page.get_by_test_id("comparison-report")).to_contain_text("清场时间")
            expect(page.get_by_test_id("comparison-report")).to_contain_text("峰值密度")
            expect(page.get_by_test_id("comparison-report")).to_contain_text("滞留人数")
            expect(page.get_by_test_id("report-evidence-timeline")).to_be_visible()
            page.get_by_test_id("report-jump-control").first.click()
            expect(page.get_by_test_id("report-replay-position")).to_contain_text("已定位")

            page.locator(".experiment-decision select").select_option("reject")
            page.locator(".experiment-decision textarea").fill("候选没有稳定改善，拒绝采用。")
            page.locator(".experiment-decision input").fill("Browser QA")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/decision") and response.request.method == "POST"
                )
            ) as decision_response:
                page.get_by_test_id("save-decision").click()
            assert decision_response.value.ok
            with page.expect_download() as report_download:
                page.get_by_test_id("export-report").click()
            report_path = tmp_path / "comparison.zip"
            report_download.value.save_as(report_path)
            with ZipFile(report_path) as archive:
                assert "decision-report.html" in archive.namelist()
                exported_html = archive.read("decision-report.html").decode("utf-8")
                assert "候选没有稳定改善" in exported_html
                assert "管控事件" in exported_html
                assert "water_barrier" in exported_html
                bundle_baseline = json.loads(archive.read("baseline.analysis-case.json"))
                assert bundle_baseline["semantic_fingerprint"].startswith(baseline_fingerprint)
                bundle_baseline_path = tmp_path / "bundle-baseline.analysis-case.json"
                bundle_baseline_path.write_bytes(archive.read("baseline.analysis-case.json"))

            page.reload(wait_until="domcontentloaded", timeout=60_000)
            _create_compact_station(page)
            page.get_by_test_id("import-baseline").set_input_files(bundle_baseline_path)
            expect(page.locator(".experiment-case code").first).to_have_text(baseline_fingerprint)
            expect(page.get_by_test_id("control-measure-water_barrier")).to_be_visible()
            expect(page.locator(".control-plan-lock")).to_have_text("案例已冻结")
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
    expect(page.get_by_test_id("generate-station")).to_be_disabled()
    expect(page.get_by_test_id("generate-station")).to_be_enabled(timeout=15_000)


def _configure_small_demand(page: Page) -> None:
    page.get_by_test_id("palette-flow-entry_flow").click()
    page.get_by_test_id("palette-flow-exit_flow").click()
    page.get_by_test_id("operation-entry_count_hour").fill("120")
    page.get_by_test_id("operation-exit_count_hour").fill("60")
    expect(page.get_by_test_id("save-baseline")).to_be_enabled(timeout=15_000)
