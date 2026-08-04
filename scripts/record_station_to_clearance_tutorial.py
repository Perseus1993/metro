from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import Locator, Page, expect, sync_playwright

from metro_station_designer.server import DesignInspectorHandler, ROOT


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "tutorial"


def record_tutorial() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = OUTPUT_DIR / f"metro_v02_station_to_clearance_{stamp}.webm"
    screenshot_path = OUTPUT_DIR / f"metro_v02_clearance_result_{stamp}.png"
    raw_dir = OUTPUT_DIR / f"raw_{stamp}"
    raw_dir.mkdir(parents=True, exist_ok=True)

    handler = partial(DesignInspectorHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/inspector.html"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, slow_mo=80)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(raw_dir),
                record_video_size={"width": 1600, "height": 900},
                locale="zh-CN",
                color_scheme="light",
            )
            page = context.new_page()
            page.set_default_timeout(20_000)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            video = page.video
            _install_tutorial_layer(page)
            _build_station(page)
            _configure_evacuation_experiment(page)
            report_text = _run_to_clearance(page)
            page.screenshot(path=str(screenshot_path), full_page=False)
            _chapter(page, "教程完成", "已从站型选择运行到清场报告，可继续导出实验包复跑。", 4_000)
            page.close()
            context.close()
            if video is None:
                raise RuntimeError("Playwright video recording was not initialized")
            video.save_as(video_path)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    return {
        "status": "ok",
        "video": str(video_path.resolve()),
        "screenshot": str(screenshot_path.resolve()),
        "clearance_confirmed": "清场 3/3" in report_text,
        "report_excerpt": report_text[:240],
    }


def _build_station(page: Page) -> None:
    expect(page.get_by_test_id("station-setup-wizard")).to_be_visible()
    _chapter(page, "1 · 选择站型", "从预设中选择“单层小型普通站”，适合快速疏散实验。")
    _click(page, page.get_by_test_id("station-preset-compact_single"))
    expect(page.get_by_test_id("station-setup-wizard")).to_be_hidden(timeout=15_000)

    _chapter(page, "2 · 生成站点", "根据站型自动生成出入口、闸机、站台和可步行区域。")
    _click(page, page.get_by_test_id("generate-station"), wait_ms=2_500)
    expect(page.get_by_test_id("generate-station")).to_be_enabled(timeout=15_000)

    _chapter(page, "3 · 配置客流", "加入进站与出站需求，并设置每小时人数。")
    _click(page, page.get_by_test_id("palette-flow-entry_flow"))
    _click(page, page.get_by_test_id("palette-flow-exit_flow"))
    _fill(page, page.get_by_test_id("operation-entry_count_hour"), "120")
    _fill(page, page.get_by_test_id("operation-exit_count_hour"), "60")
    expect(page.get_by_test_id("save-baseline")).to_be_enabled(timeout=15_000)


def _configure_evacuation_experiment(page: Page) -> None:
    _chapter(page, "4 · 加载疏散模板", "模板锁定同一案例与 3 个种子，只比较两个路由算法。")
    _click(page, page.get_by_test_id("load-algorithm-template"), wait_ms=1_800)
    _fill(page, page.get_by_test_id("experiment-horizonMinutes"), "4")
    _fill(page, page.get_by_test_id("experiment-tickSeconds"), "10")
    _fill(page, page.get_by_test_id("experiment-initialPlatformPersons"), "1")

    _chapter(page, "5 · 设置管控时间轴", "依次加入水马、设施关闭和人员引导，并设置开始/结束时刻。")
    for test_id in (
        "control-add-water_barrier",
        "control-add-access_closure",
        "control-add-staff_guidance",
    ):
        _click(page, page.get_by_test_id(test_id), wait_ms=800)
    _fill(page, page.get_by_test_id("control-geometry-x_m"), "5")
    _fill(page, page.get_by_test_id("control-geometry-y_m"), "5")
    _select(page, page.get_by_test_id("control-measure-access_closure").locator("select"), 3)
    _select(page, page.get_by_test_id("control-measure-staff_guidance").locator("select"), 2)
    for test_id, value in (
        ("control-start-water_barrier", "60"),
        ("control-end-water_barrier", "90"),
        ("control-start-access_closure", "120"),
        ("control-end-access_closure", "150"),
        ("control-start-staff_guidance", "180"),
        ("control-end-staff_guidance", "210"),
    ):
        _fill(page, page.get_by_test_id(test_id), value, wait_ms=450)
    expect(page.get_by_test_id("control-plan-valid")).to_be_visible()


def _run_to_clearance(page: Page) -> str:
    _chapter(page, "6 · 冻结实验基准", "保存站型、客流、时间轴和种子，确保两种算法输入完全一致。")
    with page.expect_response(
        lambda response: response.url.endswith("/api/analysis-cases/baseline")
    ) as response_info:
        _click(page, page.get_by_test_id("save-baseline"), wait_ms=1_000)
    response = response_info.value
    if not response.ok:
        raise RuntimeError(f"baseline rejected: {response.json()}")

    _chapter(page, "7 · 选择并预检算法", "使用内置最短路与示例 Dijkstra；候选参数设为 1.5。")
    expect(page.get_by_test_id("algorithm-config")).to_be_visible()
    _fill(page, page.get_by_test_id("algorithm-candidate-parameters"), '{"cost_multiplier": 1.5}')
    _click(page, page.get_by_test_id("algorithm-preflight"), wait_ms=1_200)
    expect(page.get_by_test_id("algorithm-preflight-status")).to_contain_text("2/2 算法兼容")

    _chapter(page, "8 · 运行 2×3 配对实验", "两个算法分别使用种子 7、42、99，共运行 6 次。", 2_000)
    _click(page, page.get_by_test_id("run-comparison"), wait_ms=1_000)
    _chapter(page, "仿真运行中", "系统正在比较清场、密度、排队、滞留和算法耗时。", 2_500)
    report = page.get_by_test_id("comparison-report")
    expect(report).to_be_visible(timeout=90_000)
    expect(report).to_contain_text("失败 0.0%")
    expect(report).to_contain_text("清场 3/3")
    _spotlight(page, report)
    _chapter(
        page,
        "9 · 查看清场结果",
        "基准与候选均完成 3/3 清场；报告同时保留耗时、失败率和决策日志。",
        5_000,
    )
    return report.inner_text()


def _install_tutorial_layer(page: Page) -> None:
    page.add_style_tag(
        content="""
        .tutorial-focus { outline: 4px solid #ffb000 !important; outline-offset: 5px; }
        #tutorial-card { position: fixed; z-index: 999999; top: 20px; left: 50%;
          transform: translateX(-50%); width: 720px; padding: 14px 20px; border-radius: 14px;
          color: white; background: rgba(10, 28, 52, .94); box-shadow: 0 10px 30px #0006;
          font: 18px/1.5 "Microsoft YaHei", sans-serif; text-align: center; pointer-events: none; }
        #tutorial-card strong { display: block; color: #ffd166; font-size: 24px; }
        #tutorial-cursor { position: fixed; z-index: 1000000; width: 24px; height: 24px;
          border: 4px solid white; border-radius: 50%; background: #e63946; box-shadow: 0 2px 8px #0008;
          transform: translate(-50%, -50%); transition: left .45s ease, top .45s ease; pointer-events: none; }
        """
    )
    page.evaluate(
        """() => {
          const card = document.createElement('div'); card.id = 'tutorial-card'; document.body.append(card);
          const cursor = document.createElement('div'); cursor.id = 'tutorial-cursor'; document.body.append(cursor);
        }"""
    )


def _chapter(page: Page, title: str, detail: str, wait_ms: int = 2_200) -> None:
    page.evaluate(
        """([title, detail]) => {
          const card = document.querySelector('#tutorial-card');
          card.style.display = 'block';
          card.innerHTML = `<strong>${title}</strong>${detail}`;
        }""",
        [title, detail],
    )
    page.wait_for_timeout(wait_ms)


def _spotlight(page: Page, locator: Locator) -> None:
    locator.scroll_into_view_if_needed()
    page.wait_for_timeout(350)
    page.evaluate(
        "() => document.querySelectorAll('.tutorial-focus').forEach(el => el.classList.remove('tutorial-focus'))"
    )
    locator.evaluate(
        """el => { const r = el.getBoundingClientRect(); el.classList.add('tutorial-focus');
          const c = document.querySelector('#tutorial-cursor'); c.style.left = `${r.left + r.width / 2}px`;
          c.style.top = `${r.top + r.height / 2}px`; }"""
    )
    page.wait_for_timeout(650)


def _click(page: Page, locator: Locator, *, wait_ms: int = 1_100) -> None:
    _spotlight(page, locator)
    locator.click()
    page.wait_for_timeout(wait_ms)


def _fill(page: Page, locator: Locator, value: str, *, wait_ms: int = 700) -> None:
    _spotlight(page, locator)
    locator.fill(value)
    page.wait_for_timeout(wait_ms)


def _select(page: Page, locator: Locator, index: int) -> None:
    _spotlight(page, locator)
    locator.select_option(index=index)
    page.wait_for_timeout(800)


if __name__ == "__main__":
    print(json.dumps(record_tutorial(), ensure_ascii=False, indent=2))
