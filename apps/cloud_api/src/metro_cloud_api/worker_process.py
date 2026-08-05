from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import psutil

from .store import JobStore


@dataclass(frozen=True)
class ProcessOutcome:
    return_code: int
    error: dict[str, Any] | None
    peak_rss_bytes: int
    runner_kind: str | None
    runner_version: str | None


class ChildProcessMonitor:
    def __init__(
        self,
        store: JobStore,
        *,
        timeout_seconds: float,
        max_rss_bytes: int,
    ) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.max_rss_bytes = max_rss_bytes

    def run(self, job_id: str, kind: str, spec_path: Path, output_dir: Path) -> ProcessOutcome:
        process = subprocess.Popen(
            [sys.executable, "-m", "metro_cloud_api.child", kind, str(spec_path), str(output_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=os.name != "nt",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )
        assert process.stdout is not None
        messages: queue.Queue[str | None] = queue.Queue()
        threading.Thread(
            target=_read_lines, args=(process.stdout, messages), daemon=True
        ).start()
        return self._monitor(job_id, process, messages, output_dir / "run.log")

    def _monitor(
        self,
        job_id: str,
        process: subprocess.Popen[str],
        messages: queue.Queue[str | None],
        log_path: Path,
    ) -> ProcessOutcome:
        started = time.monotonic()
        peak_rss = 0
        error: dict[str, Any] | None = None
        metadata: dict[str, str] = {}
        reader_closed = False
        with log_path.open("w", encoding="utf-8") as log:
            while process.poll() is None or not reader_closed:
                reader_closed, parsed_error = self._drain(
                    job_id, messages, log, metadata, reader_closed
                )
                error = error or parsed_error
                if process.poll() is not None:
                    continue
                peak_rss = max(peak_rss, _process_tree_rss(process.pid))
                reason = self._termination_reason(job_id, started, peak_rss)
                if reason is not None:
                    error = reason
                    _terminate_process_tree(process)
                time.sleep(0.05)
        return ProcessOutcome(
            return_code=int(process.wait()),
            error=error,
            peak_rss_bytes=peak_rss,
            runner_kind=metadata.get("runner_kind"),
            runner_version=metadata.get("runner_version"),
        )

    def _drain(
        self,
        job_id: str,
        messages: queue.Queue[str | None],
        log: TextIO,
        metadata: dict[str, str],
        reader_closed: bool,
    ) -> tuple[bool, dict[str, Any] | None]:
        error = None
        while True:
            try:
                line = messages.get_nowait()
            except queue.Empty:
                return reader_closed, error
            if line is None:
                reader_closed = True
                continue
            log.write(line)
            log.flush()
            message = _protocol_message(line)
            if message is None:
                continue
            if message.get("type") == "progress":
                self.store.update_progress(
                    job_id, int(message["current"]), int(message["total"])
                )
            elif message.get("type") == "meta":
                metadata.update(
                    runner_kind=str(message["runner_kind"]),
                    runner_version=str(message["runner_version"]),
                )
                self.store.set_runner(job_id, metadata["runner_kind"], metadata["runner_version"])
            elif message.get("type") == "error":
                error = {"kind": str(message.get("kind", "runner_exception")),
                         "message": str(message.get("message", "runner failed"))}
        return reader_closed, error

    def _termination_reason(
        self, job_id: str, started: float, rss_bytes: int
    ) -> dict[str, Any] | None:
        if self.store.is_cancel_requested(job_id):
            return {"kind": "cancelled", "message": "cancel requested"}
        if time.monotonic() - started > self.timeout_seconds:
            return {"kind": "timeout", "message": "job exceeded its wall-clock deadline"}
        if rss_bytes > self.max_rss_bytes:
            return {"kind": "memory_limit", "message": "job exceeded its RSS limit"}
        return None


def _read_lines(stream: TextIO, messages: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            messages.put(line)
    finally:
        messages.put(None)


def _protocol_message(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and "type" in value else None


def _process_tree_rss(pid: int) -> int:
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
        return sum(process.memory_info().rss for process in processes if process.is_running())
    except (psutil.Error, ProcessLookupError):
        return 0


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    try:
        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
        for child in descendants:
            child.terminate()
        root.terminate()
        _, alive = psutil.wait_procs([root, *descendants], timeout=5)
        for survivor in alive:
            survivor.kill()
    except psutil.Error:
        process.kill()
