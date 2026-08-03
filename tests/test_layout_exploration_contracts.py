from __future__ import annotations

import json
from pathlib import Path

import pytest

from metro_station_acceptance.layout_exploration_evidence import (
    write_exploration_evidence,
)
from metro_station_acceptance.layout_exploration_result import (
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
    catalog_coverage,
)
from metro_station_testkit.layout_exploration_case import (
    LayoutExplorationCase,
    validate_case_catalog,
)


def _case(case_id: str = "E0-CASE") -> LayoutExplorationCase:
    return LayoutExplorationCase(
        suite_id="PM028-E0",
        case_id=case_id,
        generator_version="exploration-test.v1",
        expected_class="VALID",
        factors={"shape": "rect", "mirror": False},
    )


def test_exploration_case_round_trip_and_fingerprint() -> None:
    case = _case()
    restored = LayoutExplorationCase.from_dict(case.as_dict())
    assert restored.as_dict() == case.as_dict()
    assert restored.semantic_fingerprint == case.semantic_fingerprint


def test_invalid_case_requires_diagnostic() -> None:
    with pytest.raises(ValueError, match="diagnostic"):
        LayoutExplorationCase(
            suite_id="PM028-E0",
            case_id="invalid",
            generator_version="v1",
            expected_class="INVALID",
            factors={},
        )


def test_catalog_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        validate_case_catalog((_case(), _case()))


def test_coverage_and_evidence_are_machine_readable(tmp_path: Path) -> None:
    case = _case()
    result = ExplorationCaseResult(
        case=case,
        observed_outcome="pass",
        stages=(ExplorationStageResult("layout", "ok", checks={"valid": True}),),
        checks={"expectation_met": True},
    )
    coverage = catalog_coverage((case,))
    report = ExplorationSuiteReport(
        suite_id=case.suite_id,
        generator_version=case.generator_version,
        results=(result,),
        coverage=coverage,
        checks={"all_cases_pass": True},
    )

    write_exploration_evidence((report,), tmp_path)

    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["reports"][0]["case_count"] == 1
    assert coverage["dimensions"]["mirror"] == {"false": 1}
    assert (tmp_path / "cases" / "PM028-E0" / "E0-CASE.json").exists()
