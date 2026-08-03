"""Versioned plan for a strictly paired evacuation-routing experiment."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Mapping
from uuid import uuid4

from ..analysis_cases import AnalysisCase
from ..routing_plugins import AlgorithmManifest
from .contracts import ComparisonRunSpec


EXPERIMENT_PLAN_SCHEMA_VERSION = "experiment-plan/v1"
EVACUATION_ROUTING_AXIS = "evacuation_routing"
ALGORITHM_ROLES = ("baseline", "candidate")


@dataclass(frozen=True)
class AlgorithmSelection:
    registration_id: str
    manifest: AlgorithmManifest
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.registration_id.strip():
            raise ValueError("algorithm registration_id must not be blank")
        validated = self.manifest.validate_parameters(self.parameters)
        object.__setattr__(self, "parameters", validated)

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin_id

    @property
    def plugin_version(self) -> str:
        return self.manifest.plugin_version

    def as_dict(self) -> dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "manifest": self.manifest.as_dict(),
            "parameters": deepcopy(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AlgorithmSelection:
        manifest = payload.get("manifest")
        parameters = payload.get("parameters", {})
        if not isinstance(manifest, Mapping) or not isinstance(parameters, Mapping):
            raise ValueError("algorithm manifest and parameters must be objects")
        return cls(
            registration_id=str(payload.get("registration_id", "")),
            manifest=AlgorithmManifest.from_dict(manifest),
            parameters=dict(parameters),
        )


@dataclass(frozen=True)
class ExperimentPlan:
    plan_id: str
    analysis_case: AnalysisCase
    algorithms: tuple[AlgorithmSelection, AlgorithmSelection]
    seeds: tuple[int, ...]
    template_id: str = "evacuation-routing-comparison"
    comparison_axis: str = EVACUATION_ROUTING_AXIS
    schema_version: str = EXPERIMENT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXPERIMENT_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported experiment plan schema: {self.schema_version!r}")
        if not self.plan_id.strip() or not self.template_id.strip():
            raise ValueError("plan_id and template_id must not be blank")
        if self.comparison_axis != EVACUATION_ROUTING_AXIS:
            raise ValueError(f"unsupported comparison axis: {self.comparison_axis!r}")
        if len(self.algorithms) != 2:
            raise ValueError("V0.2 algorithm experiments require exactly two algorithms")
        identities = {(item.plugin_id, item.plugin_version) for item in self.algorithms}
        if len(identities) != 2:
            raise ValueError("algorithm selections must have distinct id/version identities")
        if self.seeds != self.analysis_case.seeds:
            raise ValueError("experiment seeds must exactly match the frozen analysis case")
        if len(self.seeds) != 3:
            raise ValueError("V0.2 paired algorithm experiments require exactly three seeds")
        if self.analysis_case.simulation.get("scenario_mode") != "evacuation":
            raise ValueError("evacuation-routing experiments require an evacuation analysis case")
        if not isinstance(self.analysis_case.simulation.get("evacuation"), dict):
            raise ValueError("evacuation-routing experiments require evacuation configuration")

    @classmethod
    def create(
        cls,
        analysis_case: AnalysisCase,
        algorithms: tuple[AlgorithmSelection, AlgorithmSelection],
        *,
        template_id: str = "evacuation-routing-comparison",
    ) -> ExperimentPlan:
        return cls(uuid4().hex, analysis_case, algorithms, analysis_case.seeds, template_id)

    @property
    def semantic_fingerprint(self) -> str:
        return _fingerprint(self.semantic_payload())

    def paired_input_fingerprint(self, seed: int) -> str:
        if seed not in self.seeds:
            raise ValueError(f"seed {seed!r} is not part of experiment plan")
        return _fingerprint(
            {
                "comparison_axis": self.comparison_axis,
                "analysis_case_fingerprint": self.analysis_case.semantic_fingerprint,
                "seed": seed,
            }
        )

    def comparison_spec(self) -> ComparisonRunSpec:
        candidate = replace(
            self.analysis_case,
            case_id=f"{self.analysis_case.case_id}--algorithm-candidate",
            name=f"{self.analysis_case.name} · algorithm candidate",
            parent_case_id=self.analysis_case.case_id,
        )
        return ComparisonRunSpec(
            experiment_id=self.plan_id,
            baseline=self.analysis_case,
            candidate=candidate,
            seeds=self.seeds,
        )

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "comparison_axis": self.comparison_axis,
            "template_id": self.template_id,
            "analysis_case_fingerprint": self.analysis_case.semantic_fingerprint,
            "seeds": list(self.seeds),
            "algorithms": [item.as_dict() for item in self.algorithms],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "template_id": self.template_id,
            "comparison_axis": self.comparison_axis,
            "semantic_fingerprint": self.semantic_fingerprint,
            "analysis_case": self.analysis_case.as_dict(),
            "seeds": list(self.seeds),
            "algorithms": [item.as_dict() for item in self.algorithms],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExperimentPlan:
        expected = payload.get("semantic_fingerprint")
        algorithms = payload.get("algorithms", ())
        analysis_case = payload.get("analysis_case")
        if not isinstance(algorithms, (list, tuple)) or not isinstance(analysis_case, Mapping):
            raise ValueError("experiment algorithms must be an array and analysis_case an object")
        selections = tuple(AlgorithmSelection.from_dict(item) for item in algorithms)
        if len(selections) != 2:
            raise ValueError("V0.2 algorithm experiments require exactly two algorithms")
        plan = cls(
            plan_id=str(payload.get("plan_id", "")),
            analysis_case=AnalysisCase.from_dict(analysis_case),
            algorithms=(selections[0], selections[1]),
            seeds=tuple(int(seed) for seed in payload.get("seeds", ())),
            template_id=str(payload.get("template_id", "evacuation-routing-comparison")),
            comparison_axis=str(payload.get("comparison_axis", EVACUATION_ROUTING_AXIS)),
            schema_version=str(payload.get("schema_version", "")),
        )
        if expected and expected != plan.semantic_fingerprint:
            raise ValueError("experiment-plan semantic fingerprint mismatch")
        return plan


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
