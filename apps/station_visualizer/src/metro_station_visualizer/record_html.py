from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a station sandbox HTML page to WebM.")
    parser.add_argument(
        "--html",
        type=Path,
        default=Path("output/metro_station_sandbox_xiaozhai_18.html"),
        help="Rendered sandbox HTML file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/metro_station_sandbox_xiaozhai_18_flow.webm"),
        help="Output WebM video path.",
    )
    parser.add_argument("--width", type=int, default=1500, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=980, help="Browser viewport height.")
    parser.add_argument(
        "--speed", type=int, default=4, choices=[1, 2, 4, 8], help="Playback speed."
    )
    parser.add_argument("--extra-ms", type=int, default=1200, help="Extra recording tail in ms.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    html_path = args.html.resolve()
    out_path = args.out.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        raise SystemExit(f"missing html: {html_path}")

    video_dir = out_path.parent / "_playwright_video"
    video_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            record_video_dir=str(video_dir),
            record_video_size={"width": args.width, "height": args.height},
        )
        page = context.new_page()
        page.goto(html_path.as_uri(), wait_until="load")
        page.wait_for_timeout(800)
        page.select_option("#speed", str(args.speed))
        page.evaluate(
            """
            () => {
              const play = document.querySelector("#play");
              const scrub = document.querySelector("#scrub");
              scrub.value = "0";
              scrub.dispatchEvent(new Event("input", { bubbles: true }));
              if (play.textContent.trim() === "Play") play.click();
            }
            """
        )
        frame_count = page.evaluate("frames.length")
        frame_interval_ms = 160 / args.speed
        wait_ms = int(frame_count * frame_interval_ms + args.extra_ms)
        page.wait_for_timeout(wait_ms)
        video = page.video
        context.close()
        browser.close()

        if video is None:
            raise SystemExit("Playwright did not produce a video handle.")
        temp_path = Path(video.path())

    if out_path.exists():
        out_path.unlink()
    temp_path.replace(out_path)
    print(f"[VIDEO] html={html_path}")
    print(f"[VIDEO] frames={frame_count} speed={args.speed}x duration_ms~{wait_ms}")
    print(f"[VIDEO] output={out_path}")


if __name__ == "__main__":
    main()
