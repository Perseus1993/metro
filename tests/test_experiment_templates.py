from __future__ import annotations

import json
from pathlib import Path

from metro_station.application.comparisons import ExperimentPlan, run_algorithm_experiment
from metro_station.application.experiment_templates import (
    ExperimentTemplate,
    experiment_template_catalog,
    validate_template_report,
)

from tests.test_algorithm_experiments import _summary


FIXTURE = Path("tests/fixtures/algorithm_experiments/experiment_plan_v1.json")


def _plan() -> ExperimentPlan:
    return ExperimentPlan.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_experiment_plan_v1_golden_round_trip() -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))

    output = _plan().as_dict()
    output.pop("semantic_fingerprint")
    output["analysis_case"].pop("semantic_fingerprint")

    assert output == source


def test_template_catalog_has_one_available_and_four_reserved_contracts() -> None:
    catalog = experiment_template_catalog()

    assert [item.status for item in catalog].count("available") == 1
    assert [item.status for item in catalog].count("reserved") == 4
    assert ExperimentTemplate.from_dict(catalog[0].as_dict()) == catalog[0]
    assert catalog[0].editable_variables == ("algorithms", "algorithm_parameters")


def test_template_mechanically_checks_pairing_and_report_completeness() -> None:
    plan = _plan()

    class Executor:
        def execute(self, analysis_case, *, seed, role, spec):
            index = 0 if role == "baseline" else 1
            return _summary(
                role,
                seed,
                plan.algorithms[index],
                plan.paired_input_fingerprint(seed),
            )

    report = run_algorithm_experiment(plan, Executor())
    result = validate_template_report(experiment_template_catalog()[0], report)

    assert result.complete is True
    assert result.errors == ()
