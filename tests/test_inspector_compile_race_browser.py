from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
from threading import Event, Lock, Thread

from playwright.sync_api import expect, sync_playwright

import metro_station_designer.server as designer_server


def test_reloading_design_cancels_stale_compile_without_leaking_error(
    monkeypatch,
) -> None:
    original_compile = designer_server.compile_react_flow_payload
    stale_compile_started = Event()
    release_stale_compile = Event()
    stale_compile_finished = Event()
    first_generated_lock = Lock()
    first_generated_pending = [True]

    def delayed_first_generated_compile(payload):
        should_delay = False
        with first_generated_lock:
            if payload.get("generate_station") is True and first_generated_pending[0]:
                first_generated_pending[0] = False
                should_delay = True
        if not should_delay:
            return original_compile(payload)
        stale_compile_started.set()
        release_stale_compile.wait(timeout=30)
        stale_compile_finished.set()
        raise ValueError("stale compile failure must not reach the new design")

    monkeypatch.setattr(
        designer_server,
        "compile_react_flow_payload",
        delayed_first_generated_compile,
    )
    handler = partial(
        designer_server.DesignInspectorHandler,
        directory=str(designer_server.ROOT),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/inspector.html"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            expect(page.get_by_test_id("station-setup-wizard")).to_be_visible()
            page.get_by_test_id("station-preset-compact_single").click()
            expect(page.get_by_test_id("station-setup-wizard")).to_be_hidden(
                timeout=15_000
            )

            page.get_by_test_id("generate-station").click()
            assert stale_compile_started.wait(timeout=5)
            page.get_by_test_id("new-station").click()
            expect(page.get_by_test_id("station-setup-wizard")).to_be_visible()
            page.get_by_test_id("station-preset-compact_single").click()
            expect(page.get_by_test_id("station-setup-wizard")).to_be_hidden(
                timeout=15_000
            )

            page.get_by_test_id("generate-station").click()
            expect(page.get_by_test_id("generate-station")).to_be_enabled(
                timeout=15_000
            )
            release_stale_compile.set()
            assert stale_compile_finished.wait(timeout=5)
            page.wait_for_timeout(250)
            expect(page.locator(".canvas-status .pill--error")).to_have_count(0)
            browser.close()
    finally:
        release_stale_compile.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
