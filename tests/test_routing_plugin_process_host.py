from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from metro_station.adapters.routing_plugins import (
    RoutingPluginProcessHost,
    validate_plugin_file,
)
from metro_station.application.routing_plugins import (
    AlgorithmManifest,
    EvacuationRoutingRequest,
    PassengerGroupFacts,
    RoutingEdge,
    RoutingNode,
    RoutingTopology,
)


EXAMPLE_MANIFEST = Path("examples/evacuation_routing_plugin/manifest.json")


def _manifest(script_name: str) -> AlgorithmManifest:
    return AlgorithmManifest(
        plugin_id="test.process",
        plugin_version="1.0.0",
        entry_point=(sys.executable, script_name),
        parameter_schema={"type": "object", "additionalProperties": False},
        capabilities=("closures", "diagnostics"),
    )


def _request() -> EvacuationRoutingRequest:
    topology = RoutingTopology(
        "host-test",
        (RoutingNode("A", "L1", 0.0, 0.0, "zone"), RoutingNode("B", "L1", 1.0, 0.0, "exit")),
        (RoutingEdge("ab", "A", "B", 1.0, "walk"),),
    )
    return EvacuationRoutingRequest(
        "host-request",
        0.0,
        "A",
        "B",
        (),
        PassengerGroupFacts(1, "evacuate_station"),
        7,
        topology,
    )


def test_standalone_example_passes_ten_process_contract_cases() -> None:
    source = (EXAMPLE_MANIFEST.parent / "plugin.py").read_text(encoding="utf-8")
    report = validate_plugin_file(EXAMPLE_MANIFEST)

    assert "import metro_station" not in source
    assert "from metro_station" not in source
    assert report.passed
    assert len(report.cases) == 10
    assert report.active_processes_after == 0


def test_timeout_is_failed_and_child_is_reaped(tmp_path: Path) -> None:
    script = tmp_path / "timeout.py"
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    host = RoutingPluginProcessHost(
        _manifest(script.name), working_directory=tmp_path, timeout_seconds=0.05
    )

    result = host.invoke(_request())

    assert result.failed
    assert result.decision_log.failure_code == "timeout"
    assert host.active_process_count == 0


def test_run_deadline_terminates_the_current_request(tmp_path: Path) -> None:
    script = tmp_path / "run_timeout.py"
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    host = RoutingPluginProcessHost(
        _manifest(script.name),
        working_directory=tmp_path,
        timeout_seconds=1.0,
        run_timeout_seconds=0.05,
    )

    result = host.invoke(_request())

    assert result.failed
    assert result.decision_log.failure_code == "run_timeout"
    assert host.active_process_count == 0


def test_crash_captures_stderr_and_does_not_raise(tmp_path: Path) -> None:
    script = tmp_path / "crash.py"
    script.write_text(
        "import sys\nprint('plugin exploded', file=sys.stderr)\nraise SystemExit(3)\n",
        encoding="utf-8",
    )
    host = RoutingPluginProcessHost(_manifest(script.name), working_directory=tmp_path)

    result = host.invoke(_request())

    assert result.failed
    assert result.decision_log.failure_code == "crash"
    assert "plugin exploded" in result.decision_log.stderr
    assert result.decision_log.diagnostics["returncode"] == 3
    assert host.active_process_count == 0


def test_protocol_failure_does_not_poison_next_invocation(tmp_path: Path) -> None:
    script = tmp_path / "flaky.py"
    script.write_text(_flaky_plugin_source(), encoding="utf-8")
    host = RoutingPluginProcessHost(_manifest(script.name), working_directory=tmp_path)

    failed = host.invoke(_request())
    succeeded = host.invoke(_request())

    assert failed.failed
    assert failed.decision_log.failure_code == "protocol_error"
    assert not succeeded.failed
    assert succeeded.response is not None
    assert succeeded.response.node_ids == ("A", "B")
    assert host.active_process_count == 0


def test_invalid_parameters_fail_before_process_start(tmp_path: Path) -> None:
    script = tmp_path / "never_started.py"
    script.write_text("raise RuntimeError('must not start')\n", encoding="utf-8")
    host = RoutingPluginProcessHost(_manifest(script.name), working_directory=tmp_path)
    request = _request()
    request = EvacuationRoutingRequest.from_dict(
        {**request.as_dict(), "parameters": {"unexpected": True}}
    )

    result = host.invoke(request)

    assert result.failed
    assert result.decision_log.failure_code == "invalid_parameters"
    assert host.active_process_count == 0


def test_cli_runs_the_public_ten_case_validator() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "metro_station",
            "validate-routing-plugin",
            str(EXAMPLE_MANIFEST),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert '"passed": true' in completed.stdout
    assert '"total": 10' in completed.stdout


def _flaky_plugin_source() -> str:
    response = {
        "schema_version": "evacuation-routing/v1",
        "request_id": "host-request",
        "status": "success",
        "node_ids": ["A", "B"],
        "edge_ids": ["ab"],
        "cost": 1.0,
        "diagnostics": {"expanded_nodes": 2, "message": "ok", "metadata": {}},
    }
    return (
        "import json\nfrom pathlib import Path\n"
        "marker = Path('already_failed')\n"
        "if not marker.exists():\n"
        "    marker.write_text('1')\n"
        "    print('not-json')\n"
        "else:\n"
        f"    print(json.dumps({json.dumps(response)}))\n"
    )
