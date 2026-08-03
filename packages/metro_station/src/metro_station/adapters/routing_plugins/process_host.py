"""One-shot JSON process host for reviewed local routing plugins."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryFile
from time import perf_counter
from typing import IO, Any

from metro_station.application.routing_plugins import (
    AlgorithmManifest,
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
    RoutingInvocationResult,
    validate_routing_response,
)

from .decision_evidence import failed_decision_log, response_decision_log


PLUGIN_INVOCATION_SCHEMA_VERSION = "routing-plugin-invocation/v1"


class RoutingPluginProcessHost:
    """Run one request per child process with bounded execution time."""

    def __init__(
        self,
        manifest: AlgorithmManifest,
        *,
        working_directory: str | Path,
        timeout_seconds: float = 2.0,
        run_timeout_seconds: float = 60.0,
    ) -> None:
        if timeout_seconds <= 0 or run_timeout_seconds <= 0:
            raise ValueError("routing plugin request and run timeouts must be > 0")
        self._manifest = manifest
        self.working_directory = Path(working_directory).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self.run_timeout_seconds = float(run_timeout_seconds)
        self._run_started = perf_counter()
        self._closed = False
        self._active_processes: set[subprocess.Popen[str]] = set()

    @property
    def manifest(self) -> AlgorithmManifest:
        return self._manifest

    @property
    def active_process_count(self) -> int:
        return len(self._active_processes)

    def invoke(self, request: EvacuationRoutingRequest) -> RoutingInvocationResult:
        started = perf_counter()
        if self._closed:
            return self._failure(request, started, "host_closed", "routing plugin host is closed")
        if self._remaining_run_seconds() <= 0:
            return self._failure(request, started, "run_timeout", "routing plugin run timed out")
        try:
            self.manifest.validate_parameters(request.parameters)
        except ValueError as exc:
            return self._failure(request, started, "invalid_parameters", str(exc))
        try:
            process, input_stream = self._start_process(self._request_payload(request))
        except OSError as exc:
            return self._failure(request, started, "startup_error", str(exc))
        self._active_processes.add(process)
        try:
            return self._communicate(process, request, started)
        finally:
            self._active_processes.discard(process)
            input_stream.close()

    def close(self) -> None:
        for process in tuple(self._active_processes):
            process.kill()
            process.wait()
            self._active_processes.discard(process)
        self._closed = True

    def _start_process(self, payload: str) -> tuple[subprocess.Popen[str], IO[str]]:
        input_stream = TemporaryFile(mode="w+t", encoding="utf-8", newline="\n")
        input_stream.write(payload + "\n")
        input_stream.flush()
        input_stream.seek(0)
        try:
            process = subprocess.Popen(
                self._command(),
                cwd=self.working_directory,
                stdin=input_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
        except OSError:
            input_stream.close()
            raise
        return process, input_stream

    def _command(self) -> list[str]:
        command = list(self.manifest.entry_point)
        if command[0].lower() in {"python", "python3", "python.exe"}:
            command[0] = sys.executable
        return command

    def _communicate(self, process, request, started) -> RoutingInvocationResult:
        remaining = self._remaining_run_seconds()
        timeout = min(self.timeout_seconds, max(0.001, remaining))
        timeout_code = "run_timeout" if remaining <= self.timeout_seconds else "timeout"
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            message = (
                "routing plugin run timed out"
                if timeout_code == "run_timeout"
                else "routing plugin timed out"
            )
            return self._failure(
                request,
                started,
                timeout_code,
                message,
                stderr,
                diagnostics={"timeout_seconds": timeout},
            )
        if process.returncode != 0:
            message = f"routing plugin exited with code {process.returncode}"
            return self._failure(
                request,
                started,
                "crash",
                message,
                stderr,
                diagnostics={"returncode": process.returncode},
            )
        return self._parse_response(request, stdout, stderr, started)

    @staticmethod
    def _request_payload(request: EvacuationRoutingRequest) -> str:
        return json.dumps(
            {
                "schema_version": PLUGIN_INVOCATION_SCHEMA_VERSION,
                "request": request.as_dict(),
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    def _parse_response(self, request, stdout, stderr, started):
        try:
            lines = [line for line in stdout.splitlines() if line.strip()]
            if len(lines) != 1:
                raise ValueError("routing plugin must emit exactly one JSON response line")
            payload: Any = json.loads(lines[0])
            if not isinstance(payload, dict):
                raise ValueError("routing plugin response must be a JSON object")
            response = EvacuationRoutingResponse.from_dict(payload)
            validate_routing_response(request, response)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(request, started, "protocol_error", str(exc), stderr)
        duration = (perf_counter() - started) * 1_000.0
        log = response_decision_log(self.manifest, request, response, duration, stderr=stderr)
        return RoutingInvocationResult(response, log)

    def _failure(self, request, started, code, message, stderr="", diagnostics=None):
        duration = (perf_counter() - started) * 1_000.0
        log = failed_decision_log(
            self.manifest,
            request,
            duration,
            code=code,
            message=message,
            stderr=stderr,
            diagnostics=diagnostics,
        )
        return RoutingInvocationResult(None, log)

    def _remaining_run_seconds(self) -> float:
        return self.run_timeout_seconds - (perf_counter() - self._run_started)
