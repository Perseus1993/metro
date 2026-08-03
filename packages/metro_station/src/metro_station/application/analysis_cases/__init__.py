"""Versioned analysis-case contracts and use cases."""

from .contracts import (
    ANALYSIS_CASE_SCHEMA_VERSION,
    EVIDENCE_STATUS_SCHEMA_VERSION,
    AnalysisCase,
    EvidenceStatus,
    analysis_case_fingerprint,
    create_analysis_case,
)
from .differences import CaseDifference, clone_analysis_case, diff_analysis_cases, revise_case
from .serialization import analysis_case_from_json, analysis_case_to_json

__all__ = [
    "ANALYSIS_CASE_SCHEMA_VERSION",
    "EVIDENCE_STATUS_SCHEMA_VERSION",
    "AnalysisCase",
    "CaseDifference",
    "EvidenceStatus",
    "analysis_case_fingerprint",
    "analysis_case_from_json",
    "analysis_case_to_json",
    "clone_analysis_case",
    "create_analysis_case",
    "diff_analysis_cases",
    "revise_case",
]
