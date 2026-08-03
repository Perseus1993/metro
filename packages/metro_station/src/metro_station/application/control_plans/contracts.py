"""Framework-independent contracts for scheduled station control measures."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from ..semantic_fingerprints import semantic_fingerprint
from .capabilities import validate_event_capability, validate_measure_capability


CONTROL_PLAN_SCHEMA_VERSION = "control-plan/v1"


@dataclass(frozen=True)
class ControlMeasure:
    measure_id: str
    kind: str
    label: str
    target_id: str | None = None
    level_id: str | None = None
    initially_active: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.measure_id.strip() or not self.label.strip():
            raise ValueError("measure_id and label must not be blank")
        if not isinstance(self.initially_active, bool):
            raise ValueError("initially_active must be boolean")
        if not isinstance(self.parameters, dict) or not isinstance(self.metadata, dict):
            raise ValueError("control measure parameters and metadata must be objects")
        validate_measure_capability(
            kind=self.kind,
            target_id=self.target_id,
            level_id=self.level_id,
            parameters=self.parameters,
        )

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "measure_id": self.measure_id,
            "kind": self.kind,
            "target_id": self.target_id,
            "level_id": self.level_id,
            "initially_active": self.initially_active,
            "parameters": deepcopy(self.parameters),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_payload(),
            "label": self.label,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ControlMeasure:
        values = dict(payload)
        values["parameters"] = deepcopy(values.get("parameters", {}))
        values["metadata"] = deepcopy(values.get("metadata", {}))
        return cls(**values)


@dataclass(frozen=True)
class ControlEvent:
    event_id: str
    measure_id: str
    at_seconds: int
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.measure_id.strip():
            raise ValueError("event_id and measure_id must not be blank")
        if int(self.at_seconds) < 0:
            raise ValueError("control event at_seconds must be >= 0")
        if not self.action.strip():
            raise ValueError("control event action must not be blank")
        if not isinstance(self.parameters, dict) or not isinstance(self.metadata, dict):
            raise ValueError("control event parameters and metadata must be objects")

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "measure_id": self.measure_id,
            "at_seconds": int(self.at_seconds),
            "action": self.action,
            "parameters": deepcopy(self.parameters),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.semantic_payload(), "metadata": deepcopy(self.metadata)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ControlEvent:
        values = dict(payload)
        values["parameters"] = deepcopy(values.get("parameters", {}))
        values["metadata"] = deepcopy(values.get("metadata", {}))
        return cls(**values)


@dataclass(frozen=True)
class ControlPlan:
    plan_id: str
    name: str
    measures: tuple[ControlMeasure, ...]
    events: tuple[ControlEvent, ...]
    created_at: str = field(default_factory=lambda: _timestamp())
    updated_at: str = field(default_factory=lambda: _timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONTROL_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTROL_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported control-plan schema: {self.schema_version!r}")
        if not self.plan_id.strip() or not self.name.strip():
            raise ValueError("plan_id and name must not be blank")
        measure_by_id = _unique_by_id(self.measures, "measure_id", "control measure")
        _unique_by_id(self.events, "event_id", "control event")
        for event in self.events:
            measure = measure_by_id.get(event.measure_id)
            if measure is None:
                raise ValueError(f"control event references unknown measure {event.measure_id!r}")
            validate_event_capability(measure.kind, event.action, event.parameters)

    @property
    def semantic_fingerprint(self) -> str:
        return semantic_fingerprint(self.semantic_payload())

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "measures": [measure.semantic_payload() for measure in self.measures],
            "events": [event.semantic_payload() for event in self.events],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "semantic_fingerprint": self.semantic_fingerprint,
            "measures": [measure.as_dict() for measure in self.measures],
            "events": [event.as_dict() for event in self.events],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ControlPlan:
        values = dict(payload)
        expected_fingerprint = values.pop("semantic_fingerprint", None)
        values["measures"] = tuple(ControlMeasure.from_dict(item) for item in values["measures"])
        values["events"] = tuple(ControlEvent.from_dict(item) for item in values["events"])
        values["metadata"] = deepcopy(values.get("metadata", {}))
        plan = cls(**values)
        if expected_fingerprint and expected_fingerprint != plan.semantic_fingerprint:
            raise ValueError("control-plan semantic fingerprint mismatch")
        return plan


def create_control_plan(
    *,
    name: str,
    measures: tuple[ControlMeasure, ...],
    events: tuple[ControlEvent, ...],
    metadata: Mapping[str, Any] | None = None,
) -> ControlPlan:
    return ControlPlan(
        plan_id=uuid4().hex,
        name=name,
        measures=measures,
        events=events,
        metadata=deepcopy(dict(metadata or {})),
    )


def _unique_by_id(items: tuple[Any, ...], attribute: str, label: str) -> dict[str, Any]:
    indexed = {getattr(item, attribute): item for item in items}
    if len(indexed) != len(items):
        raise ValueError(f"{label} ids must be unique")
    return indexed


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
