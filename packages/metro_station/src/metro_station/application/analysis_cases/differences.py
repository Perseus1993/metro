"""Clone, revision, and decision-relevant case differences."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .contracts import AnalysisCase


@dataclass(frozen=True)
class CaseDifference:
    path: str
    kind: str
    before: Any
    after: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "before": deepcopy(self.before),
            "after": deepcopy(self.after),
        }


def clone_analysis_case(source: AnalysisCase, *, name: str) -> AnalysisCase:
    now = _timestamp()
    return AnalysisCase(
        case_id=uuid4().hex,
        name=name,
        design=deepcopy(source.design),
        operations=deepcopy(source.operations),
        simulation=deepcopy(source.simulation),
        seeds=source.seeds,
        evidence=source.evidence,
        revision=1,
        parent_case_id=source.case_id,
        created_at=now,
        updated_at=now,
        metadata=deepcopy(source.metadata),
    )


def revise_case(
    source: AnalysisCase,
    *,
    design: Mapping[str, Any] | None = None,
    operations: Mapping[str, int | float] | None = None,
    simulation: Mapping[str, Any] | None = None,
    seeds: tuple[int, ...] | None = None,
) -> AnalysisCase:
    return replace(
        source,
        design=deepcopy(dict(design)) if design is not None else deepcopy(source.design),
        operations=dict(operations) if operations is not None else deepcopy(source.operations),
        simulation=deepcopy(dict(simulation))
        if simulation is not None
        else deepcopy(source.simulation),
        seeds=tuple(seeds) if seeds is not None else source.seeds,
        revision=source.revision + 1,
        updated_at=_timestamp(),
    )


def diff_analysis_cases(
    baseline: AnalysisCase,
    candidate: AnalysisCase,
) -> tuple[CaseDifference, ...]:
    differences: list[CaseDifference] = []
    differences.extend(
        _mapping_differences("operations", baseline.operations, candidate.operations)
    )
    differences.extend(
        _mapping_differences("simulation", baseline.simulation, candidate.simulation)
    )
    if baseline.seeds != candidate.seeds:
        differences.append(
            CaseDifference("seeds", "changed", list(baseline.seeds), list(candidate.seeds))
        )
    differences.extend(_design_differences(baseline.design, candidate.design))
    return tuple(sorted(differences, key=lambda item: (item.path, item.kind)))


def _mapping_differences(
    prefix: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[CaseDifference]:
    rows: list[CaseDifference] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) == after.get(key):
            continue
        kind = "added" if key not in before else "removed" if key not in after else "changed"
        rows.append(CaseDifference(f"{prefix}.{key}", kind, before.get(key), after.get(key)))
    return rows


def _design_differences(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[CaseDifference]:
    before_elements = _elements_by_id(before)
    after_elements = _elements_by_id(after)
    rows: list[CaseDifference] = []
    for element_id in sorted(set(before_elements) | set(after_elements)):
        previous = before_elements.get(element_id)
        current = after_elements.get(element_id)
        if previous == current:
            continue
        kind = "added" if previous is None else "removed" if current is None else "changed"
        rows.append(CaseDifference(f"design.elements.{element_id}", kind, previous, current))
    for key in ("levels", "queues", "connections"):
        if before.get(key) != after.get(key):
            rows.append(CaseDifference(f"design.{key}", "changed", before.get(key), after.get(key)))
    return rows


def _elements_by_id(payload: Mapping[str, Any]) -> dict[str, Any]:
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        return {}
    return {
        str(element["id"]): deepcopy(element)
        for element in elements
        if isinstance(element, dict) and element.get("id")
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
