from __future__ import annotations

import json
from dataclasses import replace
from threading import Thread
import time

import pyarrow.parquet as pq

from metro_cloud_api.artifacts import ArtifactStore
from metro_cloud_api.catalog import Catalog
from metro_cloud_api.spec import resolve_spec
from metro_cloud_api.store import JobStore
from metro_cloud_api.worker import Worker


def _enqueue(settings, job_id: str, payload: dict) -> None:
    settings.ensure_directories()
    store = JobStore(settings.database_path)
    store.initialize()
    artifacts = ArtifactStore(settings.jobs_dir)
    resolved = resolve_spec(payload, Catalog.load(settings.catalog_path), settings.max_agents)
    artifacts.prepare(job_id)
    artifacts.write_specs(job_id, payload, resolved)
    store.create(job_id, payload, resolved)


def test_worker_fake_runner_end_to_end(settings) -> None:
    payload = {
        "spec_version": "0.1",
        "horizon_minutes": 5, "demand_minutes": 5,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
        "group_size": 5, "trajectory_sample_seconds": 10,
    }
    _enqueue(settings, "job", payload)
    worker = Worker(settings)
    assert worker.run_once()
    job = worker.store.get("job")
    assert job["status"] == "succeeded"
    summary = json.loads((settings.jobs_dir / "job" / "summary.json").read_text("utf-8"))
    assert summary["result"]["passenger_agent_count"] == 1
    assert summary["result"]["person_count"] == 5
    assert summary["result"]["simulated_seconds"] == 300
    trajectories = pq.read_table(settings.jobs_dir / "job" / "trajectories.parquet")
    assert trajectories.column_names[0] == "agent_id"
    assert not (settings.jobs_dir / "job" / "_result.json").exists()


def test_worker_recovers_interrupted_job_with_summary(settings) -> None:
    payload = {
        "spec_version": "0.1",
        "entry_count_hour": 60,
        "exit_count_hour": 0,
        "transfer_count_hour": 0,
    }
    _enqueue(settings, "lost", payload)
    worker = Worker(settings)
    assert worker.store.claim_next() is not None
    assert worker.recover_interrupted() == 1
    summary = json.loads((settings.jobs_dir / "lost" / "summary.json").read_text("utf-8"))
    assert summary["status"] == "failed"
    assert summary["error"]["kind"] == "worker_lost"
    assert summary["result"]["passenger_agent_count"] is None
    assert summary["result"]["trajectory_rows"] is None
    assert summary["result"]["peak_rss_bytes"] is None
    assert summary["timing"]["wall_seconds"] is not None


def test_timeout_writes_summary_and_hides_partial_results(settings, monkeypatch) -> None:
    monkeypatch.setenv("METRO_FAKE_SECONDS_PER_TICK", "0.02")
    slow = replace(settings, job_timeout_seconds=0.05)
    payload = {
        "spec_version": "0.1",
        "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
    }
    _enqueue(slow, "timeout", payload)
    worker = Worker(slow)
    worker.run_once()
    summary = json.loads((slow.jobs_dir / "timeout" / "summary.json").read_text("utf-8"))
    assert summary["status"] == "failed"
    assert summary["error"]["kind"] == "timeout"
    assert summary["result"]["passenger_agent_count"] is None
    assert summary["result"]["event_rows"] is None
    assert isinstance(summary["result"]["peak_rss_bytes"], int)
    assert summary["timing"]["wall_seconds"] is not None
    assert not (slow.jobs_dir / "timeout" / "trajectories.parquet").exists()


def test_running_cancel_terminates_job(settings, monkeypatch) -> None:
    monkeypatch.setenv("METRO_FAKE_SECONDS_PER_TICK", "0.02")
    payload = {
        "spec_version": "0.1",
        "horizon_minutes": 1, "demand_minutes": 1,
        "entry_count_hour": 60, "exit_count_hour": 0, "transfer_count_hour": 0,
    }
    _enqueue(settings, "cancel", payload)
    worker = Worker(settings)
    thread = Thread(target=worker.run_once)
    thread.start()
    deadline = time.monotonic() + 5
    while worker.store.get("cancel")["status"] != "running":
        if time.monotonic() > deadline:
            raise TimeoutError("worker did not claim the job")
        time.sleep(0.01)
    worker.store.request_cancel("cancel")
    thread.join(timeout=10)
    assert not thread.is_alive()
    job = worker.store.get("cancel")
    assert job["status"] == "cancelled"
    summary = json.loads((settings.jobs_dir / "cancel" / "summary.json").read_text("utf-8"))
    assert summary["error"]["kind"] == "cancelled"
    assert summary["status"] == "cancelled"
    assert summary["result"]["total_agent_count"] is None
