from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


DEFAULT_DEBUG_LOG_PATH = (
    Path(__file__).resolve().parents[3] / "output" / "station_designer_debug.jsonl"
)
DEFAULT_MAX_LOG_BYTES = 100 * 1024 * 1024
MAX_READ_EVENTS = 2_000


class DesignDebugLog:
    def __init__(
        self,
        path: Path = DEFAULT_DEBUG_LOG_PATH,
        *,
        max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    ) -> None:
        self.path = Path(path)
        self.max_bytes = max(1_024, int(max_bytes))
        self._lock = Lock()

    def record(
        self,
        action: str,
        *,
        source: str,
        session_id: str,
        status: str = "info",
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        client_sequence: int | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "session_id": _bounded_text(session_id, fallback="unknown", limit=128),
            "source": _bounded_text(source, fallback="server", limit=32),
            "action": _bounded_text(action, fallback="unknown", limit=160),
            "status": _bounded_text(status, fallback="info", limit=32),
            "request_id": _bounded_text(request_id, fallback="", limit=128) or None,
            "client_sequence": _optional_nonnegative_int(client_sequence),
            "details": _json_safe(details or {}),
        }
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(encoded))
            with self.path.open("ab") as destination:
                destination.write(encoded)
        return event

    def read(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(MAX_READ_EVENTS, int(limit)))
        session_filter = str(session_id or "").strip()
        with self._lock:
            if not self.path.is_file():
                return []
            retained: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
            with self.path.open("r", encoding="utf-8") as source:
                for raw_line in source:
                    event = _parse_event(raw_line)
                    if event is None:
                        continue
                    if session_filter and event.get("session_id") != session_filter:
                        continue
                    retained.append(event)
            return list(retained)

    def export_jsonl(self, *, session_id: str | None = None) -> bytes:
        session_filter = str(session_id or "").strip()
        with self._lock:
            if not self.path.is_file():
                return b""
            if not session_filter:
                return self.path.read_bytes()
            lines: list[str] = []
            with self.path.open("r", encoding="utf-8") as source:
                for raw_line in source:
                    event = _parse_event(raw_line)
                    if event is None or event.get("session_id") != session_filter:
                        continue
                    lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.is_file():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        backup = self.path.with_suffix(f"{self.path.suffix}.1")
        backup.unlink(missing_ok=True)
        self.path.replace(backup)


def _parse_event(raw_line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(raw_line)
    except (TypeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _bounded_text(value: Any, *, fallback: str, limit: int) -> str:
    text = str(value or fallback).strip()
    return text[:limit]


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


DESIGN_DEBUG_LOG = DesignDebugLog()
