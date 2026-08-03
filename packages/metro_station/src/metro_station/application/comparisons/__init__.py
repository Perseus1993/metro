"""Reproducible baseline/candidate comparison use cases."""

from .contracts import (
    COMPARISON_RUN_SPEC_SCHEMA_VERSION,
    RUN_SUMMARY_SCHEMA_VERSION,
    ComparisonRunSpec,
    RunSummary,
)
from .experiment import (
    ALGORITHM_ROLES,
    EVACUATION_ROUTING_AXIS,
    EXPERIMENT_PLAN_SCHEMA_VERSION,
    AlgorithmSelection,
    ExperimentPlan,
)
from .metrics import build_run_summary, crowd_safety_metrics
from .report_contracts import (
    COMPARISON_REPORT_SCHEMA_VERSION,
    AnalystDecision,
    ComparisonReport,
)
from .reporting import build_comparison_report
from .service import (
    ComparisonCaseExecutor,
    ComparisonProgress,
    run_algorithm_experiment,
    run_comparison,
)

__all__ = [
    "COMPARISON_REPORT_SCHEMA_VERSION",
    "COMPARISON_RUN_SPEC_SCHEMA_VERSION",
    "RUN_SUMMARY_SCHEMA_VERSION",
    "AnalystDecision",
    "AlgorithmSelection",
    "ALGORITHM_ROLES",
    "ComparisonCaseExecutor",
    "ComparisonProgress",
    "ComparisonReport",
    "ComparisonRunSpec",
    "EVACUATION_ROUTING_AXIS",
    "EXPERIMENT_PLAN_SCHEMA_VERSION",
    "ExperimentPlan",
    "RunSummary",
    "build_comparison_report",
    "build_run_summary",
    "crowd_safety_metrics",
    "run_comparison",
    "run_algorithm_experiment",
]
