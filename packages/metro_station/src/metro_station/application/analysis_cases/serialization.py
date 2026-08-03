"""JSON serialization for versioned analysis cases."""

from __future__ import annotations

import json
from typing import Any

from .contracts import AnalysisCase


def analysis_case_to_json(case: AnalysisCase, *, indent: int | None = 2) -> str:
    return json.dumps(case.as_dict(), ensure_ascii=False, indent=indent, sort_keys=True) + "\n"


def analysis_case_from_json(source: str | bytes) -> AnalysisCase:
    try:
        payload: Any = json.loads(source)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid analysis-case JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("analysis-case JSON must contain an object")
    return AnalysisCase.from_dict(payload)
