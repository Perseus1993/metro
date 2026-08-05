from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .artifact_contract import validate_runner_artifacts
from .config import Settings
from .spec import runner_spec
from .store import JobStore, utc_now
from .summary import build_summary
from .worker_process import ChildProcessMonitor, ProcessOutcome


class Worker:
    def __init__(self, settings: Settings) -> None:
        settings.ensure_directories()
        self.settings = settings
        self.store = JobStore(settings.database_path)
        self.store.initialize()
        self.artifacts = ArtifactStore(settings.jobs_dir)
        self.monitor = ChildProcessMonitor(
            self.store,
            timeout_seconds=settings.job_timeout_seconds,
            max_rss_bytes=settings.max_rss_bytes,
        )

    def recover_interrupted(self) -> int:
        recovered = 0
        for job in self.store.interrupted_jobs():
            error = {
                "kind": "worker_lost",
                "message": "worker restarted while the job was running",
            }
            self.artifacts.remove_private_and_partial(job["id"])
            self.artifacts.remove_failed_results(job["id"])
            finished_at = utc_now()
            recovered_job = {
                **job,
                "status": "failed",
                "finished_at": finished_at,
                "error": error,
            }
            self.artifacts.write_summary(
                job["id"], build_summary(recovered_job, self.artifacts.job_dir(job["id"]))
            )
            self.store.finish(job["id"], "failed", error=error, finished_at=finished_at)
            recovered += 1
        return recovered

    def run_once(self) -> bool:
        job = self.store.claim_next()
        if job is None:
            return False
        self._execute(job)
        return True

    def run_forever(self) -> None:
        self.recover_interrupted()
        while True:
            if not self.run_once():
                time.sleep(self.settings.poll_seconds)

    def _execute(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        output_dir = self.artifacts.job_dir(job_id)
        spec_path = output_dir / "_runner_spec.json"
        spec_path.write_text(
            json.dumps(runner_spec(job["resolved_spec"]), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        outcome: ProcessOutcome | None = None
        status = "failed"
        error: dict[str, Any] | None = None
        try:
            outcome = self.monitor.run(
                job_id, self.settings.runner_kind, spec_path, output_dir
            )
            status, error = self._classify(outcome, output_dir)
        except Exception as exc:  # noqa: BLE001 - preserve a durable job result
            error = {"kind": "worker_error", "message": f"{type(exc).__name__}: {exc}"}
        finally:
            spec_path.unlink(missing_ok=True)
            refreshed = self.store.get(job_id)
            if status != "succeeded":
                self.artifacts.remove_failed_results(job_id)
            peak_rss = outcome.peak_rss_bytes if outcome is not None else None
            finished_at = utc_now()
            terminal_job = {
                **refreshed,
                "status": status,
                "finished_at": finished_at,
                "error": error,
            }
            self.artifacts.write_summary(
                job_id,
                build_summary(
                    terminal_job,
                    self.artifacts.job_dir(job_id),
                    peak_rss_bytes=peak_rss,
                ),
            )
            self.artifacts.remove_private_and_partial(job_id)
            self.store.finish(job_id, status, error=error, finished_at=finished_at)
            succeeded = [
                item["id"]
                for item in reversed(self.store.list(limit=10_000))
                if item["status"] == "succeeded"
            ]
            self.artifacts.enforce_budget(succeeded, self.settings.max_artifact_bytes)

    def _classify(
        self, outcome: ProcessOutcome, output_dir: Path
    ) -> tuple[str, dict[str, Any] | None]:
        if outcome.error is not None:
            if outcome.error["kind"] == "cancelled":
                return "cancelled", outcome.error
            return "failed", outcome.error
        required = [output_dir / "trajectories.parquet", output_dir / "events.parquet",
                    output_dir / "_result.json"]
        if outcome.return_code == 0 and all(path.is_file() for path in required):
            contract = validate_runner_artifacts(output_dir)
            if contract["valid"]:
                return "succeeded", None
            return "failed", {
                "kind": "invalid_artifact",
                "message": "; ".join(contract["errors"]),
            }
        return "failed", {
            "kind": "nonzero_exit" if outcome.return_code else "missing_artifact",
            "message": f"runner exited with code {outcome.return_code}",
        }
