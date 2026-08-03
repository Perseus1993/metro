from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from metro_station.application.semantic_fingerprints import semantic_fingerprint


LAYOUT_EXPLORATION_CASE_SCHEMA_VERSION = "layout_exploration_case.v1"
EXPECTED_CLASSES = frozenset({"VALID", "INVALID", "STRESS", "AUDIT"})


@dataclass(frozen=True)
class LayoutExplorationCase:
    suite_id: str
    case_id: str
    generator_version: str
    expected_class: str
    factors: Mapping[str, Any]
    seed: int = 42
    expected_failure_stage: str | None = None
    expected_diagnostic_codes: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ("PM-028",)
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LAYOUT_EXPLORATION_CASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LAYOUT_EXPLORATION_CASE_SCHEMA_VERSION:
            raise ValueError(f"unsupported exploration case schema {self.schema_version!r}")
        if not self.suite_id.strip() or not self.case_id.strip():
            raise ValueError("suite_id and case_id must not be blank")
        if not self.generator_version.strip():
            raise ValueError("generator_version must not be blank")
        if self.expected_class not in EXPECTED_CLASSES:
            raise ValueError(f"unknown expected_class {self.expected_class!r}")
        if self.expected_class == "INVALID" and not self.expected_diagnostic_codes:
            raise ValueError("INVALID cases must declare expected diagnostic codes")
        if self.expected_failure_stage and self.expected_class != "INVALID":
            raise ValueError("only INVALID cases may declare expected_failure_stage")
        if not self.requirements or any(not item.strip() for item in self.requirements):
            raise ValueError("requirements must contain non-blank ids")

    @property
    def semantic_fingerprint(self) -> str:
        return semantic_fingerprint(self.semantic_payload())

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "case_id": self.case_id,
            "generator_version": self.generator_version,
            "expected_class": self.expected_class,
            "factors": deepcopy(dict(self.factors)),
            "seed": int(self.seed),
            "expected_failure_stage": self.expected_failure_stage,
            "expected_diagnostic_codes": list(self.expected_diagnostic_codes),
            "requirements": list(self.requirements),
            "notes": self.notes,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "semantic_fingerprint": self.semantic_fingerprint,
            **self.semantic_payload(),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LayoutExplorationCase:
        values = dict(payload)
        expected = values.pop("semantic_fingerprint", None)
        values["factors"] = deepcopy(dict(values.get("factors", {})))
        values["expected_diagnostic_codes"] = tuple(
            str(item) for item in values.get("expected_diagnostic_codes", ())
        )
        values["requirements"] = tuple(str(item) for item in values.get("requirements", ()))
        values["metadata"] = deepcopy(dict(values.get("metadata", {})))
        case = cls(**values)
        if expected is not None and str(expected) != case.semantic_fingerprint:
            raise ValueError("layout exploration case semantic fingerprint mismatch")
        return case


def validate_case_catalog(cases: tuple[LayoutExplorationCase, ...]) -> None:
    if not cases:
        raise ValueError("exploration case catalog must not be empty")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("exploration case ids must be unique")
    suite_ids = {case.suite_id for case in cases}
    if len(suite_ids) != 1:
        raise ValueError("an exploration catalog must contain exactly one suite_id")

