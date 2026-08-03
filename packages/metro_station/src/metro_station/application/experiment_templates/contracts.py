"""Contracts for guided, reproducible experiment setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..comparisons import ComparisonReport, EVACUATION_ROUTING_AXIS, ExperimentPlan


EXPERIMENT_TEMPLATE_SCHEMA_VERSION = "experiment-template/v1"
TEMPLATE_STATUSES = frozenset({"available", "reserved"})


@dataclass(frozen=True)
class ExperimentTemplate:
    template_id: str
    version: str
    title: str
    research_question: str
    comparison_axis: str
    status: str
    seeds: tuple[int, ...]
    locked_variables: tuple[str, ...]
    editable_variables: tuple[str, ...]
    required_metrics: tuple[str, ...]
    schema_version: str = EXPERIMENT_TEMPLATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXPERIMENT_TEMPLATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported experiment template schema: {self.schema_version!r}")
        if self.status not in TEMPLATE_STATUSES:
            raise ValueError(f"unsupported experiment template status: {self.status!r}")
        if not all((self.template_id.strip(), self.version.strip(), self.title.strip())):
            raise ValueError("template id, version, and title must not be blank")
        if set(self.locked_variables) & set(self.editable_variables):
            raise ValueError("locked and editable experiment variables must not overlap")

    def validate_plan(self, plan: ExperimentPlan) -> None:
        if self.status != "available":
            raise ValueError(f"experiment template is reserved: {self.template_id}")
        if plan.template_id != self.template_id:
            raise ValueError("experiment plan template_id does not match template")
        if plan.comparison_axis != self.comparison_axis:
            raise ValueError("experiment plan changes a locked comparison axis")
        if plan.seeds != self.seeds:
            raise ValueError("experiment plan changes the template paired seeds")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "version": self.version,
            "title": self.title,
            "research_question": self.research_question,
            "comparison_axis": self.comparison_axis,
            "status": self.status,
            "seeds": list(self.seeds),
            "locked_variables": list(self.locked_variables),
            "editable_variables": list(self.editable_variables),
            "required_metrics": list(self.required_metrics),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExperimentTemplate:
        values = dict(payload)
        for key in ("seeds", "locked_variables", "editable_variables", "required_metrics"):
            values[key] = tuple(values.get(key, ()))
        return cls(**values)


@dataclass(frozen=True)
class TemplateCheckResult:
    complete: bool
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"complete": self.complete, "errors": list(self.errors)}


def experiment_template_catalog() -> tuple[ExperimentTemplate, ...]:
    locked = (
        "analysis_case.design",
        "analysis_case.operations",
        "analysis_case.simulation",
        "analysis_case.control_plan",
        "seeds",
    )
    metrics = (
        "clearance_time_s",
        "peak_density_persons_m2",
        "max_gate_queue",
        "max_vertical_queue",
        "stuck_agents",
        "routing_compute_duration_ms",
        "stability_rate",
        "failure_rate",
    )
    return (
        ExperimentTemplate(
            "evacuation-routing-comparison",
            "1.0.0",
            "疏散算法比较",
            "同一案例与配对种子下，路由算法如何改变疏散结果与运行稳定性？",
            EVACUATION_ROUTING_AXIS,
            "available",
            (7, 42, 99),
            locked,
            ("algorithms", "algorithm_parameters"),
            metrics,
        ),
        *_reserved_templates(locked),
    )


def validate_template_report(
    template: ExperimentTemplate,
    report: ComparisonReport,
) -> TemplateCheckResult:
    errors: list[str] = []
    plan = report.experiment_plan
    if plan is None:
        errors.append("report_missing_experiment_plan")
        return TemplateCheckResult(False, tuple(errors))
    try:
        template.validate_plan(plan)
    except ValueError as exc:
        errors.append(str(exc))
    expected_runs = len(plan.algorithms) * len(plan.seeds)
    if len(report.runs) != expected_runs:
        errors.append("report_run_matrix_incomplete")
    execution = report.aggregate.get("algorithm_execution", {})
    if set(execution) != {"baseline", "candidate"}:
        errors.append("report_algorithm_aggregate_incomplete")
    if not all(run.paired_input_fingerprint for run in report.runs):
        errors.append("report_pairing_fingerprint_missing")
    return TemplateCheckResult(not errors, tuple(errors))


def _reserved_templates(locked: tuple[str, ...]) -> tuple[ExperimentTemplate, ...]:
    definitions = (
        ("water-barrier-position", "水马位置", "管控位置如何改变清场与瓶颈？"),
        ("exit-choice", "出口选择", "出口策略如何改变分流？"),
        ("vertical-split", "楼梯/扶梯分流", "垂直设施分流如何改变排队？"),
        ("facility-failure", "设施故障", "设施故障如何改变疏散韧性？"),
    )
    return tuple(
        ExperimentTemplate(
            template_id,
            "0.1.0-reserved",
            title,
            question,
            "reserved",
            "reserved",
            (7, 42, 99),
            locked,
            (),
            (),
        )
        for template_id, title, question in definitions
    )
