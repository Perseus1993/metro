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
from playwright.sync_api import Page, sync_playwright

from water_barrier_tutorial_cards import (
    install_story_layer,
    pause_playback,
    resume_playback,
    show_caption,
    show_result,
    show_story_image,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "tutorial"
VISUALIZER_PATH = "apps/station_visualizer/src/metro_station_visualizer/animation_demo.html"
TRACK_PATH = "/output/tutorial/water_barrier_clearance_120_tracks.js"
PLACEMENT_IMAGE = "/output/tutorial/image2_water_barrier_placement.png"
SIMULATION_IMAGE = "/output/tutorial/image2_water_barrier_simulation.png"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def record_water_barrier_tutorial() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = OUTPUT_DIR / f"water_barrier_raw_{stamp}"
    webm_path = OUTPUT_DIR / f"water_barrier_clearance_tutorial_{stamp}.webm"
    mp4_path = OUTPUT_DIR / f"water_barrier_clearance_tutorial_{stamp}.mp4"
    screenshot_path = OUTPUT_DIR / f"water_barrier_clearance_result_{stamp}.png"
    raw_dir.mkdir(parents=True, exist_ok=True)

    server, worker = _serve_repo()
    url = (
        f"http://127.0.0.1:{server.server_address[1]}/{VISUALIZER_PATH}"
        f"?file={TRACK_PATH}&mode=clearance"
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(raw_dir),
                record_video_size={"width": 1600, "height": 900},
                locale="zh-CN",
            )
            page = context.new_page()
            page.set_default_timeout(120_000)
            page.goto(url, wait_until="load")
            video = page.video
            _prepare_replay(page)
            _record_story(page, screenshot_path)
            page.close()
            context.close()
            if video is None:
                raise RuntimeError("Playwright video recording was not initialized")
            video.save_as(webm_path)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    _convert_to_mp4(webm_path, mp4_path)
    return {
        "status": "ok",
        "video": str(mp4_path.resolve()),
        "screenshot": str(screenshot_path.resolve()),
        "baseline_clearance": "10:35",
        "water_barrier_clearance": "13:10",
        "difference": "2:35",
        "remaining_people": 0,
    }


def _prepare_replay(page: Page) -> None:
    page.wait_for_function("() => typeof window.demoSetObstacleVisible === 'function'")
    page.wait_for_function(
        "() => document.querySelector('#stageStatus')?.dataset.visible === 'false'"
    )
    page.evaluate(
        """() => {
          window.demoSetPlaybackMode('clearance', { pause: true });
          window.demoJumpTo(0);
          window.demoSetSpeed(24);
          window.demoSetObstacleVisible('water_barrier_tutorial', true);
        }"""
    )
    install_story_layer(page)


def _record_story(page: Page, screenshot_path: Path) -> None:
    show_story_image(
        page,
        PLACEMENT_IMAGE,
        "额外案例：把水马放在站台中间，让人流分开走。",
        4_000,
    )
    show_caption(page, "橙色这一条，就是刚放好的水马。", 2_000)
    show_story_image(
        page,
        SIMULATION_IMAGE,
        "开始以后，小人会从水马两边绕开，不会直接穿过去。",
        4_000,
    )
    show_caption(page, "下面看实际过程。中间部分会加速播放。", 1_800)
    page.locator("#restart").click()
    _wait_for_clearance(page)
    show_result(page)
    page.screenshot(path=str(screenshot_path), full_page=False)
    page.wait_for_timeout(5_000)


def _wait_for_clearance(page: Page) -> None:
    milestones = [
        (60, "已经走了一半，水马附近的人还在慢慢通过。"),
        (10, "只剩最后几个人了。"),
    ]
    shown: set[int] = set()
    deadline = monotonic() + 90
    while monotonic() < deadline:
        remaining = int(page.locator("#peopleCount").inner_text())
        status = page.locator("#clearanceStatus").inner_text()
        if remaining == 0 and "已清场" in status:
            return
        for threshold, message in milestones:
            if remaining <= threshold and threshold not in shown:
                shown.add(threshold)
                pause_playback(page)
                show_caption(page, message, 1_800)
                resume_playback(page)
        page.wait_for_timeout(250)
    raise RuntimeError("water-barrier playback did not reach cleared state")


def _serve_repo() -> tuple[ThreadingHTTPServer, Thread]:
    handler = partial(QuietHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _convert_to_mp4(webm_path: Path, mp4_path: Path) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i",
            str(webm_path),
            "-c:v",
            "libx264",
            "-crf",
            "21",
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
    print(json.dumps(record_water_barrier_tutorial(), ensure_ascii=False, indent=2))
