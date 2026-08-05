from __future__ import annotations

import pytest
from pydantic import ValidationError

from metro_cloud_api.catalog import Catalog
from metro_cloud_api.spec import JobSpec, resolve_spec


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
