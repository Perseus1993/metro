"""Stable semantic fingerprints for analysis cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..semantic_fingerprints import semantic_fingerprint

if TYPE_CHECKING:
    from .contracts import AnalysisCase


def analysis_case_fingerprint(case: AnalysisCase) -> str:
    return semantic_fingerprint(case.semantic_payload())
