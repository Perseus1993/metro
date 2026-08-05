from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .job_records import compact_json, deserialize_job, utc_now


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    submitted_spec TEXT NOT NULL,
                    resolved_spec TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    runner_kind TEXT,
                    runner_version TEXT,
                    error_json TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at)"
            )

    def create(
        self,
        job_id: str,
        submitted_spec: dict[str, Any],
        resolved_spec: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO jobs(
                    id, status, submitted_spec, resolved_spec, created_at, progress_total
                ) VALUES (?, 'queued', ?, ?, ?, ?)""",
                (
                    job_id,
                    compact_json(submitted_spec),
                    compact_json(resolved_spec),
                    utc_now(),
                    int(resolved_spec["_derived"]["horizon_seconds"]),
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return deserialize_job(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [deserialize_job(row) for row in rows]

    def count_active(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["n"])

    def queue_position(self, job_id: str) -> int | None:
        job = self.get(job_id)
        if job["status"] != "queued":
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS n FROM jobs
                WHERE status = 'queued' AND created_at < ?""",
                (job["created_at"],),
            ).fetchone()
        return int(row["n"]) + 1

    def claim_next(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id FROM jobs WHERE status = 'queued' AND cancel_requested = 0
                ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            started_at = utc_now()
            updated = connection.execute(
                """UPDATE jobs SET status = 'running', started_at = ?
                WHERE id = ? AND status = 'queued'""",
                (started_at, row["id"]),
            ).rowcount
            if updated != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        return deserialize_job(claimed)

    def update_progress(self, job_id: str, current: int, total: int) -> None:
        safe_total = max(1, total)
        safe_current = max(0, min(current, safe_total))
        with self.connect() as connection:
            connection.execute(
                """UPDATE jobs SET progress_current = ?, progress_total = ?
                WHERE id = ? AND status = 'running'""",
                (safe_current, safe_total, job_id),
            )

    def set_runner(self, job_id: str, kind: str, version: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET runner_kind = ?, runner_version = ? WHERE id = ?",
                (kind, version, job_id),
            )

    def request_cancel(
        self,
        job_id: str,
        *,
        on_queued_cancel: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == "queued":
                finished_at = utc_now()
                error = {"kind": "cancelled", "message": "cancelled before execution"}
                if on_queued_cancel is not None:
                    prospective = deserialize_job(row)
                    prospective.update(
                        status="cancelled",
                        cancel_requested=True,
                        finished_at=finished_at,
                        error=error,
                    )
                    on_queued_cancel(prospective)
                connection.execute(
                    """UPDATE jobs SET status = 'cancelled', cancel_requested = 1,
                    finished_at = ?, error_json = ? WHERE id = ?""",
                    (
                        finished_at,
                        compact_json(error),
                        job_id,
                    ),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,)
                )
        return self.get(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        return bool(self.get(job_id)["cancel_requested"])

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        with self.connect() as connection:
            connection.execute(
                """UPDATE jobs SET status = ?, finished_at = ?, error_json = ?,
                progress_current = CASE WHEN ? = 'succeeded' THEN progress_total
                                        ELSE progress_current END
                WHERE id = ?""",
                (
                    status, finished_at or utc_now(),
                    None if error is None else compact_json(error),
                    status, job_id,
                ),
            )

    def interrupted_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = 'running' ORDER BY created_at"
            ).fetchall()
        return [deserialize_job(row) for row in rows]
