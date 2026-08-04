from __future__ import annotations

import json
import subprocess
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic

import imageio_ffmpeg
from playwright.sync_api import Page, expect, sync_playwright

from metro_station_designer.server import DesignInspectorHandler, ROOT as DESIGNER_ROOT
from metro_station_visualizer.config import ROOT as VISUALIZER_ROOT
from record_station_to_clearance_tutorial import (
    _chapter,
    _click,
    _fill,
    _install_tutorial_layer,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "tutorial"
TRACK_FILE = "assets/experiment_tracks/clearance_120_tracks.js"
_IMAGE2_STYLE = """
#image2-explainer { position: fixed; inset: 0; z-index: 2000001; display: none;
  place-items: center; padding: 56px; background: rgba(3, 12, 24, .78);
  backdrop-filter: blur(7px); font-family: "Microsoft YaHei", sans-serif; color: #eaf4ff; }
.image2-board { width: min(1220px, calc(100vw - 112px)); padding: 38px 44px 42px;
  border: 1px solid rgba(126, 201, 255, .45); border-radius: 28px;
  background: linear-gradient(145deg, rgba(13, 35, 61, .98), rgba(5, 20, 38, .98));
  box-shadow: 0 28px 80px rgba(0, 0, 0, .52); }
.image2-kicker { color: #78d8ff; font-size: 18px; letter-spacing: .12em; font-weight: 700; }
.image2-title { margin-top: 8px; color: white; font-size: 42px; font-weight: 800; }
.image2-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 30px 0; }
.image2-metrics > div { min-height: 126px; padding: 20px; border-radius: 18px;
  background: rgba(255, 255, 255, .07); border: 1px solid rgba(255, 255, 255, .12); }
.image2-metrics span { display: block; color: #9eb5c9; font-size: 17px; }
.image2-metrics strong { display: block; margin-top: 8px; color: #ffd166; font-size: 40px; }
.image2-flow { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 24px; border-radius: 18px; background: rgba(0, 0, 0, .18); }
.image2-flow div { flex: 1; padding: 16px 10px; border-radius: 12px; text-align: center;
  background: rgba(52, 152, 219, .18); border: 1px solid rgba(120, 216, 255, .3);
  font-size: 19px; font-weight: 700; }
.image2-flow b { color: #78d8ff; font-size: 28px; }
.image2-note { margin: 26px 4px 0; color: #d9e7f2; font-size: 22px; line-height: 1.6; }
#image2-explainer.is-cleared .metric-verdict strong,
#image2-explainer.is-cleared .metric-remaining strong { color: #65e69b; }
"""


def record_people_clearance() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    webm_path = OUTPUT_DIR / f"metro_station_people_clearance_{stamp}.webm"
    mp4_path = OUTPUT_DIR / f"metro_station_people_clearance_{stamp}.mp4"
    screenshot_path = OUTPUT_DIR / f"metro_station_people_cleared_{stamp}.png"
    image2_path = OUTPUT_DIR / f"metro_station_clearance_image2_{stamp}.png"
    raw_dir = OUTPUT_DIR / f"people_clearance_raw_{stamp}"
    raw_dir.mkdir(parents=True, exist_ok=True)

    designer, designer_worker = _serve(DESIGNER_ROOT, DesignInspectorHandler)
    visualizer, visualizer_worker = _serve(VISUALIZER_ROOT, SimpleHTTPRequestHandler)
    designer_url = f"http://127.0.0.1:{designer.server_address[1]}/inspector.html"
    visualizer_url = (
        f"http://127.0.0.1:{visualizer.server_address[1]}/animation_demo.html"
        f"?file={TRACK_FILE}&mode=clearance"
    )
    lead_in_seconds = 0.0
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, slow_mo=25)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(raw_dir),
                record_video_size={"width": 1600, "height": 900},
                locale="zh-CN",
                color_scheme="light",
            )
            page = context.new_page()
            recording_started = monotonic()
            page.set_default_timeout(20_000)
            page.goto(designer_url, wait_until="domcontentloaded", timeout=60_000)
            video = page.video
            _install_tutorial_layer(page)
            _prepare_two_level_station(page)
            lead_in_seconds = monotonic() - recording_started
            _open_clearance_replay(page, visualizer_url)
            result = _wait_until_people_cleared(page, image2_path)
            page.screenshot(path=str(screenshot_path), full_page=False)
            page.close()
            context.close()
            if video is None:
                raise RuntimeError("Playwright video recording was not initialized")
            video.save_as(webm_path)
            browser.close()
    finally:
        _stop(designer, designer_worker)
        _stop(visualizer, visualizer_worker)

    _convert_to_mp4(webm_path, mp4_path, lead_in_seconds=lead_in_seconds)
    return {
        "status": "ok",
        "video": str(mp4_path.resolve()),
        "webm": str(webm_path.resolve()),
        "screenshot": str(screenshot_path.resolve()),
        "image2": str(image2_path.resolve()),
        **result,
    }


def _prepare_two_level_station(page: Page) -> None:
    expect(page.get_by_test_id("station-setup-wizard")).to_be_visible()
    _chapter(page, "1 · 快速选型", "二层标准普通站：站厅层、站台层和垂直交通。", 900)
    _click(page, page.get_by_test_id("station-preset-standard_two"), wait_ms=300)
    expect(page.get_by_test_id("station-setup-wizard")).to_be_hidden(timeout=15_000)

    _chapter(page, "2 · 生成站点", "自动生成出入口、闸机、楼扶梯和站台。", 700)
    _click(page, page.get_by_test_id("generate-station"), wait_ms=800)
    expect(page.get_by_test_id("generate-station")).to_be_enabled(timeout=15_000)

    _chapter(page, "3 · 配置客流", "设置进站 120、出站 0，准备清场轨迹。", 700)
    _click(page, page.get_by_test_id("palette-flow-entry_flow"), wait_ms=250)
    _click(page, page.get_by_test_id("palette-flow-exit_flow"), wait_ms=250)
    _fill(page, page.get_by_test_id("operation-entry_count_hour"), "120", wait_ms=250)
    _fill(page, page.get_by_test_id("operation-exit_count_hour"), "0", wait_ms=250)
    expect(page.get_by_test_id("run-simulation")).to_be_enabled(timeout=15_000)

    _chapter(page, "4 · 生成轨迹", "启动仿真并进入小人清场回放。", 800)
    _click(page, page.get_by_test_id("run-simulation"), wait_ms=300)
    expect(page.locator(".simulation-launch .simulation-result")).to_be_visible(timeout=90_000)
    _chapter(page, "轨迹已就绪", "切换到可视化，观察小人离站。", 1_000)


def _open_clearance_replay(page: Page, url: str) -> None:
    page.goto(url, wait_until="load", timeout=60_000)
    page.wait_for_function("() => typeof window.demoSetSpeed === 'function'", timeout=60_000)
    page.wait_for_function(
        "() => document.querySelector('#stageStatus')?.dataset.visible === 'false'",
        timeout=60_000,
    )
    _install_tutorial_layer(page)
    page.evaluate(
        """() => {
          window.demoSetPlaybackMode('clearance', { pause: true });
          window.demoJumpTo(0);
          window.demoSetSpeed(16);
        }"""
    )
    _chapter(
        page,
        "5 · 小人清场回放",
        "非关键过程使用 16×；关键人数节点暂停讲解。",
        1_500,
    )
    page.evaluate("() => document.querySelector('#restart').click()")
    page.wait_for_function("() => Number(document.querySelector('#peopleCount')?.textContent) > 0")
    _hide_chapter(page)


def _wait_until_people_cleared(page: Page, image2_path: Path) -> dict[str, object]:
    _show_image2_explainer(
        page,
        stage="起点",
        remaining=120,
        note="回放从 120 人开始；后续只统计仍位于站内的乘客。",
        hold_ms=1_800,
    )
    milestones = [
        (60, "过半离站", "累计离站达到一半，当前在站人数持续下降。"),
        (10, "接近完成", "最后 10 人继续沿疏散路线移动到出口。"),
    ]
    shown: set[int] = set()
    deadline = monotonic() + 110
    while monotonic() < deadline:
        remaining = int(page.locator("#peopleCount").inner_text())
        status = page.locator("#clearanceStatus").inner_text()
        if remaining == 0 and "已清场" in status:
            break
        for threshold, stage, note in milestones:
            if remaining <= threshold and threshold not in shown:
                shown.add(threshold)
                _show_image2_explainer(
                    page,
                    stage=stage,
                    remaining=remaining,
                    note=note,
                    hold_ms=2_000,
                    screenshot_path=image2_path if threshold == 60 else None,
                )
        page.wait_for_timeout(350)
    else:
        raise RuntimeError("passenger playback did not reach cleared state")

    detail = page.locator("#clearanceDetail").inner_text()
    _show_image2_explainer(
        page,
        stage="清场完成",
        remaining=0,
        note=f"当前在站归零，系统判定“已清场”。{detail}。",
        hold_ms=4_000,
        resume=False,
    )
    return {
        "remaining_people": 0,
        "clearance_status": page.locator("#clearanceStatus").inner_text(),
        "clearance_detail": detail,
    }


def _show_image2_explainer(
    page: Page,
    *,
    stage: str,
    remaining: int,
    note: str,
    hold_ms: int,
    screenshot_path: Path | None = None,
    resume: bool = True,
) -> None:
    """Pause playback and place a deterministic infographic over the live scene."""
    if page.locator("#play").get_attribute("aria-label") == "暂停":
        page.locator("#play").click()
    exited = max(0, 120 - remaining)
    cleared = remaining == 0
    page.evaluate(
        """([stage, remaining, exited, note, cleared]) => {
          let overlay = document.querySelector('#image2-explainer');
          if (!overlay) {
            overlay = document.createElement('section');
            overlay.id = 'image2-explainer';
            overlay.innerHTML = `
              <div class="image2-board">
                <div class="image2-kicker">IMAGE 2 · 清场判定讲解图</div>
                <div class="image2-title"></div>
                <div class="image2-metrics">
                  <div><span>初始人数</span><strong>120</strong></div>
                  <div class="metric-exited"><span>累计离站</span><strong></strong></div>
                  <div class="metric-remaining"><span>当前在站</span><strong></strong></div>
                  <div class="metric-verdict"><span>判定</span><strong></strong></div>
                </div>
                <div class="image2-flow">
                  <div>读取乘客轨迹</div><b>→</b><div>越过出口边界</div><b>→</b>
                  <div>当前在站递减</div><b>→</b><div>剩余 0 即清场</div>
                </div>
                <p class="image2-note"></p>
              </div>`;
            document.body.append(overlay);
          }
          overlay.querySelector('.image2-title').textContent = `关键节点：${stage}`;
          overlay.querySelector('.metric-exited strong').textContent = exited;
          overlay.querySelector('.metric-remaining strong').textContent = remaining;
          overlay.querySelector('.metric-verdict strong').textContent = cleared ? '已清场' : '疏散中';
          overlay.querySelector('.image2-note').textContent = note;
          overlay.classList.toggle('is-cleared', cleared);
          overlay.style.display = 'grid';
        }""",
        [stage, remaining, exited, note, cleared],
    )
    if page.locator("#image2-explainer").get_attribute("data-styled") != "true":
        page.add_style_tag(content=_IMAGE2_STYLE)
        page.locator("#image2-explainer").evaluate("el => el.dataset.styled = 'true'")
    if screenshot_path is not None:
        page.screenshot(path=str(screenshot_path), full_page=False)
    page.wait_for_timeout(hold_ms)
    page.locator("#image2-explainer").evaluate("el => el.style.display = 'none'")
    if resume and page.locator("#play").get_attribute("aria-label") == "播放":
        page.locator("#play").click()


def _hide_chapter(page: Page) -> None:
    page.evaluate("() => document.querySelector('#tutorial-card').style.display = 'none'")


def _serve(root: Path, handler_type):
    handler = partial(handler_type, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _stop(server: ThreadingHTTPServer, worker: Thread) -> None:
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)


def _convert_to_mp4(
    webm_path: Path,
    mp4_path: Path,
    *,
    lead_in_seconds: float,
    lead_in_speed: float = 2.2,
) -> None:
    cutoff = max(0.0, lead_in_seconds)
    filter_complex = (
        f"[0:v]trim=start=0:end={cutoff:.3f},setpts=PTS/{lead_in_speed}[lead];"
        f"[0:v]trim=start={cutoff:.3f},setpts=PTS-STARTPTS[body];"
        "[lead][body]concat=n=2:v=1:a=0,fps=25,format=yuv420p[v]"
    )
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i",
            str(webm_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(mp4_path),
        ],
        check=True,
    )


if __name__ == "__main__":
    print(json.dumps(record_people_clearance(), ensure_ascii=False, indent=2))
