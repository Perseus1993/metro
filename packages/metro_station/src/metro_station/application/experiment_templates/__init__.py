"""Versioned experiment templates and mechanical completion checks."""

from .contracts import (
    EXPERIMENT_TEMPLATE_SCHEMA_VERSION,
    ExperimentTemplate,
    TemplateCheckResult,
    experiment_template_catalog,
    validate_template_report,
)

__all__ = [
    "EXPERIMENT_TEMPLATE_SCHEMA_VERSION",
    "ExperimentTemplate",
    "TemplateCheckResult",
    "experiment_template_catalog",
    "validate_template_report",
]
