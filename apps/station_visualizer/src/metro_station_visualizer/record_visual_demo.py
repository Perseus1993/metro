from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

try:  # Support both package execution and direct script execution.
    from .config import OUTPUT_DIR, ROOT
except ImportError:  # pragma: no cover
    from config import OUTPUT_DIR, ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record the metro station visual demo.")
    parser.add_argument(
        "--html",
        type=Path,
        default=ROOT / "animation_demo.html",
        help="Demo HTML file.",
    )
    parser.add_argument(
        "--webm",
        type=Path,
        default=OUTPUT_DIR / "metro_station_visual_demo_flow.webm",
        help="Intermediate WebM output.",
    )
    parser.add_argument(
        "--mp4",
        type=Path,
        default=OUTPUT_DIR / "metro_station_visual_demo_flow.mp4",
        help="Final MP4 output.",
    )
    parser.add_argument("--width", type=int, default=1500, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=844, help="Browser viewport height.")
    parser.add_argument(
        "--start-sec", type=float, default=20.0, help="Animation time to start recording from."
    )
    parser.add_argument(
        "--duration-sec", type=float, default=39.0, help="Recording duration in seconds."
    )
    parser.add_argument(
        "--speed", type=int, default=1, choices=[1, 2, 4], help="Animation playback speed."
    )
    return parser


def record_webm(
    html_path: Path,
    webm_path: Path,
    width: int,
    height: int,
    start_sec: float,
    duration_sec: float,
    speed: int,
) -> None:
    webm_path.parent.mkdir(parents=True, exist_ok=True)
    video_dir = webm_path.parent / "_visual_demo_video"
    video_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(video_dir),
            record_video_size={"width": width, "height": height},
        )
        page = context.new_page()
        page.goto(html_path.as_uri(), wait_until="load")
        page.wait_for_timeout(700)
        page.evaluate("(speed) => window.demoSetSpeed(speed)", speed)
        page.evaluate("(seconds) => window.demoJumpTo(seconds)", start_sec)
        page.wait_for_timeout(int(duration_sec * 1000))
        video = page.video
        context.close()
        browser.close()

        if video is None:
            raise RuntimeError("Playwright did not return a video handle.")
        temp_path = Path(video.path())

    if webm_path.exists():
        webm_path.unlink()
    temp_path.replace(webm_path)


def convert_to_mp4(webm_path: Path, mp4_path: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    mp4_path.parent.mkdir(parents=True, exist_ok=True)
    if mp4_path.exists():
        mp4_path.unlink()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(webm_path),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-vf",
        "fps=30",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    args = build_parser().parse_args()
    html_path = args.html.resolve()
    webm_path = args.webm.resolve()
    mp4_path = args.mp4.resolve()

    if not html_path.exists():
        raise SystemExit(f"missing html: {html_path}")

    record_webm(
        html_path=html_path,
        webm_path=webm_path,
        width=args.width,
        height=args.height,
        start_sec=args.start_sec,
        duration_sec=args.duration_sec,
        speed=args.speed,
    )
    convert_to_mp4(webm_path, mp4_path)
    print(f"[VISUAL DEMO] html={html_path}")
    print(f"[VISUAL DEMO] webm={webm_path}")
    print(f"[VISUAL DEMO] mp4={mp4_path}")


if __name__ == "__main__":
    main()
