from __future__ import annotations

import json
import subprocess
import time
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import metro_station_designer.server as server_module
from metro_station_designer.debug_log import DesignDebugLog


def test_design_debug_log_persists_filters_and_exports_jsonl(tmp_path: Path) -> None:
    debug_log = DesignDebugLog(tmp_path / "designer.jsonl")
    first = debug_log.record(
        "setup.level_selected",
        source="client",
        session_id="session-a",
        client_sequence=1,
        details={"levels": 3},
    )
    debug_log.record(
        "design.compiled",
        source="server",
        session_id="session-b",
        status="ok",
        details={"summary": {"status": "ok"}},
    )
    last = debug_log.record(
        "station.generated",
        source="server",
        session_id="session-a",
        status="ok",
        request_id="request-1",
        details={"generated_snapshot": {"document": {"id": "station"}}},
    )

    session_events = debug_log.read(limit=20, session_id="session-a")
    exported = [
        json.loads(line) for line in debug_log.export_jsonl(session_id="session-a").splitlines()
    ]

    assert [event["event_id"] for event in session_events] == [
        first["event_id"],
        last["event_id"],
    ]
    assert exported == session_events
    assert debug_log.read(limit=1)[0]["action"] == "station.generated"
    assert last["request_id"] == "request-1"


def test_debug_log_rotates_without_losing_the_new_event(tmp_path: Path) -> None:
    path = tmp_path / "designer.jsonl"
    debug_log = DesignDebugLog(path, max_bytes=1_024)

    for index in range(8):
        debug_log.record(
            "layout.nodes_changed",
            source="client",
            session_id="rotation",
            details={"index": index, "payload": "x" * 300},
        )

    assert path.is_file()
    assert path.with_suffix(".jsonl.1").is_file()
    assert debug_log.read(limit=20)[-1]["details"]["index"] == 7


def test_frontend_debug_outbox_retries_in_sequence_after_transport_failure() -> None:
    module_uri = (
        Path("apps/station_designer/src/metro_station_designer/debug_event_log.js").resolve().as_uri()
    )
    script = f"""
      const storage = new Map();
      globalThis.window = {{}};
      globalThis.sessionStorage = {{
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
      }};
      const attempts = [];
      globalThis.fetch = async (_url, options) => {{
        attempts.push(JSON.parse(options.body));
        if (attempts.length === 1) return {{ ok: false, status: 503, statusText: 'offline' }};
        return {{ ok: true, status: 201, statusText: 'created' }};
      }};
      const module = await import({json.dumps(module_uri)});
      await Promise.all([
        module.recordDebugEvent('facility.dropped', {{ node_id: 'a' }}),
        module.recordDebugEvent('station.generate_clicked', {{}}),
      ]);
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const outbox = JSON.parse(storage.get('metro-station-debug-outbox') || '[]');
      process.stdout.write(JSON.stringify({{
        attempts: attempts.map((event) => event.sequence),
        outbox,
      }}));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result == {"attempts": [1, 1, 2], "outbox": []}


def test_debug_http_api_correlates_client_generate_and_simulation_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    debug_log = DesignDebugLog(tmp_path / "designer.jsonl")
    monkeypatch.setattr(server_module, "DESIGN_DEBUG_LOG", debug_log)
    monkeypatch.setattr(
        server_module,
        "simulate_design_payload",
        lambda payload, progress_callback=None: {
            "status": "ok",
            "metrics": {"completed_agents": 1},
            "trajectory_report": {"pass_fail": "pass"},
            "compile_summary": {"status": "ok"},
            "error": None,
        },
    )
    handler = partial(server_module.DesignInspectorHandler, directory=str(server_module.ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    session_id = "debug-http-session"
    try:
        client_response = _request_json(
            f"{base_url}/api/debug/events",
            method="POST",
            session_id=session_id,
            payload={
                "action": "setup.level_selected",
                "sequence": 1,
                "details": {"levels": 2},
            },
        )
        design = server_module.build_design_payload("single_level_terminal")
        generate_payload = {
            "template_id": "single_level_terminal",
            "nodes": design["react_flow"]["nodes"],
            "edges": design["react_flow"]["edges"],
            "operations": {"entry_count_hour": 1, "minutes": 1},
            "generate_station": True,
        }
        generated = _request_json(
            f"{base_url}/api/compile",
            method="POST",
            session_id=session_id,
            payload=generate_payload,
        )
        simulation = _request_json(
            f"{base_url}/api/simulate",
            method="POST",
            session_id=session_id,
            payload=generate_payload,
        )
        _wait_for_job(base_url, simulation["job_id"], session_id)
        query = urlencode({"session_id": session_id, "limit": 100})
        log_payload = _request_json(
            f"{base_url}/api/debug/events?{query}",
            session_id=session_id,
        )
        export_request = Request(
            f"{base_url}/api/debug/export?{urlencode({'session_id': session_id})}",
            headers={"X-Debug-Session": session_id},
        )
        with urlopen(export_request, timeout=5) as response:
            exported_lines = response.read().decode("utf-8").splitlines()
            export_content_type = response.headers["Content-Type"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    actions = [event["action"] for event in log_payload["events"]]
    generated_event = next(
        event for event in log_payload["events"] if event["action"] == "station.generated"
    )

    assert client_response["accepted"] is True
    assert generated["summary"]["status"] != "error"
    assert {
        "setup.level_selected",
        "station.generate_requested",
        "station.generated",
        "simulation.requested",
        "simulation.queued",
        "simulation.completed",
    } <= set(actions)
    assert generated_event["details"]["generated_snapshot"]["document"]
    assert len(exported_lines) == len(log_payload["events"])
    assert export_content_type.startswith("application/x-ndjson")


def _wait_for_job(base_url: str, job_id: str, session_id: str) -> None:
    for _ in range(50):
        result = _request_json(
            f"{base_url}/api/simulate/jobs/{job_id}",
            session_id=session_id,
        )
        if result["status"] not in {"queued", "running"}:
            return
        time.sleep(0.02)
    raise AssertionError("simulation debug test job did not finish")


def _request_json(
    url: str,
    *,
    method: str = "GET",
    session_id: str,
    payload: dict | None = None,
) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Debug-Session": session_id,
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
