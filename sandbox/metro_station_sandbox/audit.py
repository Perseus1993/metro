from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    source: str
    code: str
    severity: str = "info"
    count: int = 1
    step: int | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        parts = [
            "[AUDIT]",
            f"severity={self.severity}",
            f"source={self.source}",
            f"code={self.code}",
            f"count={self.count}",
        ]
        if self.step is not None:
            parts.append(f"step={self.step}")
        if self.context:
            payload = json.dumps(self.context, ensure_ascii=False, sort_keys=True, default=str)
            parts.append(f"context={payload}")
        return " ".join(parts)


class AuditLogger:
    """Structured audit sink for diagnostic and degraded execution paths."""

    def __init__(self, *, enabled: bool = True, print_events: bool = True) -> None:
        self.enabled = enabled
        self.print_events = print_events
        self.events: list[AuditEvent] = []
        self.counts: Counter[str] = Counter()
        self._once_keys: set[tuple[Any, ...]] = set()

    def record(
        self,
        code: str,
        *,
        source: str,
        severity: str = "info",
        count: int = 1,
        step: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> AuditEvent | None:
        if not self.enabled:
            return None
        event = AuditEvent(
            source=source,
            code=code,
            severity=severity,
            count=int(count),
            step=step,
            context=dict(context or {}),
        )
        self.events.append(event)
        self.counts[code] += event.count
        if self.print_events:
            print(event.line())
        return event

    def record_once(
        self,
        code: str,
        *,
        source: str,
        severity: str = "info",
        count: int = 1,
        step: int | None = None,
        context: dict[str, Any] | None = None,
        key: tuple[Any, ...] | None = None,
    ) -> AuditEvent | None:
        dedupe_key = key or (
            source,
            code,
            json.dumps(context or {}, ensure_ascii=False, sort_keys=True, default=str),
        )
        if dedupe_key in self._once_keys:
            return None
        self._once_keys.add(dedupe_key)
        return self.record(
            code,
            source=source,
            severity=severity,
            count=count,
            step=step,
            context=context,
        )

    def summary(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))


GLOBAL_AUDIT = AuditLogger()


def audit_event(
    code: str,
    *,
    source: str,
    severity: str = "info",
    count: int = 1,
    step: int | None = None,
    context: dict[str, Any] | None = None,
) -> AuditEvent | None:
    return GLOBAL_AUDIT.record(
        code,
        source=source,
        severity=severity,
        count=count,
        step=step,
        context=context,
    )
