from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from metro_cloud_api.catalog import Catalog
from metro_cloud_api.spec import JobSpec, resolve_spec


FIXTURES = Path(__file__).parents[3] / "docs" / "cloud" / "fixtures"


def operations(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "spec_version": "0.1",
        "entry_count_hour": 300,
        "exit_count_hour": 0,
        "transfer_count_hour": 0,
    }
    payload.update(overrides)
    return payload


def test_group_size_capacity_is_agent_based(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    result = resolve_spec(operations(group_size=5), catalog, 200)
    assert result["_derived"]["estimated_passenger_agents"] == 10
    assert result["_derived"]["estimated_total_agents"] == 10


def test_evacuation_requires_divisible_initial_population() -> None:
    with pytest.raises(ValidationError, match="divisible"):
        JobSpec.model_validate(
            operations(
                scenario_mode="evacuation", entry_count_hour=0,
                initial_platform_persons=51, group_size=5,
            )
        )


def test_evacuation_rejects_regular_flow() -> None:
    with pytest.raises(ValidationError, match="flow fields"):
        JobSpec.model_validate(
            operations(scenario_mode="evacuation", initial_platform_persons=50)
        )


def test_admins_count_for_capacity_but_not_passenger_agents(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    result = resolve_spec(operations(admins=3), catalog, 200)
    assert result["_derived"]["estimated_passenger_agents"] == 50
    assert result["_derived"]["estimated_total_agents"] == 53


def test_capacity_limit_is_enforced(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    with pytest.raises(ValueError, match="exceeds limit"):
        resolve_spec(operations(entry_count_hour=1206), catalog, 200)


def test_mixed_flows_round_each_scheduler_independently(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    result = resolve_spec(
        operations(entry_count_hour=9, exit_count_hour=9, transfer_count_hour=9,
                   demand_minutes=10),
        catalog,
        200,
    )
    assert result["_derived"]["estimated_passenger_agents"] == 6


def test_nonzero_flow_that_rounds_to_no_agents_is_rejected(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    with pytest.raises(ValueError, match="rounds to zero"):
        resolve_spec(operations(entry_count_hour=1, demand_minutes=1), catalog, 200)


def test_version_is_required_and_frozen_limits_are_enforced() -> None:
    without_version = operations()
    without_version.pop("spec_version")
    with pytest.raises(ValidationError, match="spec_version"):
        JobSpec.model_validate(without_version)
    with pytest.raises(ValidationError, match="64"):
        JobSpec.model_validate(operations(label="x" * 65))
    with pytest.raises(ValidationError, match="600"):
        JobSpec.model_validate(
            operations(
                scenario_mode="evacuation",
                entry_count_hour=0,
                initial_platform_persons=50,
                alarm_delay_seconds=601,
            )
        )
    with pytest.raises(ValidationError, match="2147483647"):
        JobSpec.model_validate(operations(seed=2**31))


def test_legacy_clock_is_supported_but_alarm_is_evacuation_only() -> None:
    assert JobSpec.model_validate(operations(clock_mode="legacy_scaled")).clock_mode == (
        "legacy_scaled"
    )
    with pytest.raises(ValidationError, match="alarm_delay_seconds"):
        JobSpec.model_validate(operations(alarm_delay_seconds=1))


def test_frozen_contract_fixtures(settings) -> None:
    catalog = Catalog.load(settings.catalog_path)
    for name in ("jobspec.minimal.json", "jobspec.full.json"):
        payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert resolve_spec(payload, catalog, 200)["spec_version"] == "0.1"
    rejected = json.loads(
        (FIXTURES / "jobspec.rejected.json").read_text(encoding="utf-8")
    )
    for case in rejected["cases"]:
        with pytest.raises((ValidationError, ValueError), match=".+"):
            resolve_spec(case["spec"], catalog, 200)
