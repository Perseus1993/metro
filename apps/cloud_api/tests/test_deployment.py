from __future__ import annotations

from pathlib import Path


DEPLOY = Path(__file__).parents[1] / "deploy"


def _read(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_api_is_loopback_only_and_worker_has_hard_limits() -> None:
    api = _read("metro-cloud-api.service")
    worker = _read("metro-cloud-worker.service")

    assert "--host 127.0.0.1 --port 8000" in api
    assert "0.0.0.0" not in api
    assert "KillMode=control-group" in worker
    assert "MemoryAccounting=true" in worker
    assert "MemoryMax=3G" in worker
    assert "ReadWritePaths=/var/lib/metro-cloud" in api
    assert "ReadWritePaths=/var/lib/metro-cloud" in worker


def test_install_requires_locked_real_runner_at_expected_path() -> None:
    install = _read("install.sh")

    assert "set -euo pipefail" in install
    assert '!= "/opt/metro"' in install
    assert "uv sync --locked" in install
    assert "--package metro-cloud --extra real" in install
    assert "systemctl enable --now" in install


def test_target_checks_cover_network_load_and_sigkill_recovery() -> None:
    verify = _read("verify.sh")
    recovery = _read("verify-worker-recovery.sh")

    assert "0\\.0\\.0\\.0" in verify
    assert "127\\.0\\.0\\.1:8000" in verify
    assert "active jobs must be drained" in verify
    assert "--agents 25 50 100 200" in verify
    assert "--jobs 10 --agents 50 --runner real" in verify
    assert "--signal=SIGKILL" in recovery
    assert 'summary["error"]["kind"] == "worker_lost"' in recovery
    assert "active jobs must be drained" in recovery
    assert "metro_cloud_api[.]child" in recovery
