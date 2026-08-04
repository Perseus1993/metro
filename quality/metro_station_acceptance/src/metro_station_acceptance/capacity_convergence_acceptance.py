from __future__ import annotations

from dataclasses import replace
from typing import Any

from metro_station.adapters.simulation.compilation.spatial_capacity import (
    CAPACITY_POLICY_VERSION,
    validate_spatial_capacity_certificates,
    validate_spatial_demand_contracts,
)
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.design import create_design

from .generated_replay_contract import generated_contract_scenario


RESOURCE_DEFICIT_CODES = {
    "queue": "queues.capacity_not_materialized",
    "decision_holding": "holding.capacity_below_required",
    "platform_waiting": "platform.capacity_below_required",
    "release_apron": "release.batch_not_placeable",
    "service_corridor": "release.route_not_traversable",
    "spawn_reservoir": "capacity.demand_exceeds_storage",
}


def inspect_capacity_convergence() -> dict[str, Any]:
    """Exercise the compile boundary without scenario-by-scenario simulation.

    A certificate is a constructive safe lower bound, never a claim that an
    irregular polygon's mathematically maximal circle packing was solved.
    The monotonic probes make the convergence rule explicit: C is admitted by
    the validator and C + 1 is rejected with the resource's stable code.
    """

    document = create_design("visual_demo_station")
    scenario = generated_contract_scenario(document)
    compiled = validate_compiled_station_design(document, scenario)
    baseline_errors = _error_codes(compiled.issues)
    certificates = compiled.spatial_capacity_certificates

    facility_ids = {str(item.facility_id) for item in compiled.facilities}
    certified_facility_ids = {
        owner_id
        for owner_id in facility_ids
        if {
            item.resource_kind
            for item in certificates
            if item.owner_id == owner_id
        }
        >= {"queue", "release_apron", "service_corridor"}
    }

    monotonic_certificate_probes: list[dict[str, Any]] = []
    for resource_kind, expected_code in RESOURCE_DEFICIT_CODES.items():
        candidates = tuple(
            item
            for item in certificates
            if item.resource_kind == resource_kind
            and (
                resource_kind != "release_apron"
                or item.owner_id.startswith("vertical:")
            )
        )
        if not candidates:
            monotonic_certificate_probes.append(
                {
                    "resource_kind": resource_kind,
                    "status": "review",
                    "expected_code": expected_code,
                    "reason": "no baseline certificate",
                }
            )
            continue
        certificate = candidates[0]
        at_capacity = replace(
            certificate,
            required_body_capacity=certificate.certified_body_capacity,
        )
        over_capacity = replace(
            certificate,
            required_body_capacity=certificate.certified_body_capacity + 1,
        )
        at_codes = _error_codes(validate_spatial_capacity_certificates((at_capacity,)))
        over_codes = _error_codes(validate_spatial_capacity_certificates((over_capacity,)))
        monotonic_certificate_probes.append(
            {
                "resource_kind": resource_kind,
                "certificate_id": certificate.certificate_id,
                "certified_body_capacity": certificate.certified_body_capacity,
                "expected_code": expected_code,
                "at_capacity_error_codes": at_codes,
                "over_capacity_error_codes": over_codes,
                "status": (
                    "ok"
                    if expected_code not in at_codes and expected_code in over_codes
                    else "review"
                ),
            }
        )

    monotonic_demand_probes: list[dict[str, Any]] = []
    for contract in compiled.spatial_demand_contracts:
        expected_code = (
            "platform.capacity_below_required"
            if contract.resource_kind == "platform_waiting"
            else "capacity.demand_exceeds_storage"
        )
        at_capacity = replace(
            contract,
            required_body_capacity=contract.certified_body_capacity,
        )
        over_capacity = replace(
            contract,
            required_body_capacity=contract.certified_body_capacity + 1,
        )
        at_codes = _error_codes(validate_spatial_demand_contracts((at_capacity,)))
        over_codes = _error_codes(validate_spatial_demand_contracts((over_capacity,)))
        monotonic_demand_probes.append(
            {
                "contract_id": contract.contract_id,
                "certified_body_capacity": contract.certified_body_capacity,
                "expected_code": expected_code,
                "at_capacity_error_codes": at_codes,
                "over_capacity_error_codes": over_codes,
                "status": (
                    "ok"
                    if expected_code not in at_codes and expected_code in over_codes
                    else "review"
                ),
            }
        )

    scenario_probes = (
        _scenario_probe(
            "oversized_elevator_batch",
            document,
            replace(scenario, elevator_cabin_capacity_persons=60),
            {"release.batch_not_placeable", "release.route_not_traversable"},
        ),
        _scenario_probe(
            "arrival_demand_exceeds_storage",
            document,
            replace(scenario, entry_count_hour=100_000),
            {"capacity.demand_exceeds_storage"},
        ),
        _scenario_probe(
            "platform_service_below_demand",
            document,
            replace(
                scenario,
                entry_count_hour=3_600,
                platform_capacity_persons=1,
            ),
            {"platform.capacity_below_required"},
        ),
    )

    elevator_release_certificates = tuple(
        item
        for item in certificates
        if item.resource_kind == "release_apron"
        and item.owner_id.startswith("vertical:elevator")
    )
    elevator_prefixes_complete = bool(elevator_release_certificates) and all(
        tuple(len(plan) for plan in item.batch_plans)
        == tuple(range(1, item.certified_body_capacity + 1))
        for item in elevator_release_certificates
    )
    checks = {
        "baseline_compiles_without_capacity_errors": not baseline_errors,
        "all_six_resource_kinds_certified": set(RESOURCE_DEFICIT_CODES)
        <= {item.resource_kind for item in certificates},
        "every_facility_has_queue_release_and_corridor_certificate": (
            bool(facility_ids) and certified_facility_ids == facility_ids
        ),
        "all_certificates_use_current_policy": bool(certificates)
        and {item.policy_version for item in certificates}
        == {CAPACITY_POLICY_VERSION},
        "all_elevator_batch_prefixes_1_through_b_proved": elevator_prefixes_complete,
        "certificate_boundary_is_monotonic": bool(monotonic_certificate_probes)
        and all(item["status"] == "ok" for item in monotonic_certificate_probes),
        "demand_boundary_is_monotonic": bool(monotonic_demand_probes)
        and all(item["status"] == "ok" for item in monotonic_demand_probes),
        "real_scenario_failures_are_compile_time_diagnostics": all(
            item["status"] == "ok" for item in scenario_probes
        ),
    }
    return {
        "schema_version": "capacity_convergence.v1",
        "status": "ok" if all(checks.values()) else "review",
        "capacity_semantics": "constructive_safe_lower_bound",
        "capacity_policy_version": CAPACITY_POLICY_VERSION,
        "certificate_count": len(certificates),
        "facility_count": len(facility_ids),
        "fully_certified_facility_count": len(certified_facility_ids),
        "resource_counts": {
            resource_kind: sum(
                item.resource_kind == resource_kind for item in certificates
            )
            for resource_kind in sorted(RESOURCE_DEFICIT_CODES)
        },
        "certificate_boundary_probes": tuple(monotonic_certificate_probes),
        "demand_boundary_probes": tuple(monotonic_demand_probes),
        "scenario_probes": scenario_probes,
        "checks": checks,
    }


def _scenario_probe(
    case_id: str,
    document,
    scenario,
    expected_codes: set[str],
) -> dict[str, Any]:
    compiled = validate_compiled_station_design(document, scenario)
    actual_codes = set(_error_codes(compiled.issues))
    return {
        "case_id": case_id,
        "expected_codes": tuple(sorted(expected_codes)),
        "actual_error_codes": tuple(sorted(actual_codes)),
        "status": "ok" if expected_codes <= actual_codes else "review",
    }


def _error_codes(issues) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(issue.code)
                for issue in issues
                if getattr(issue, "severity", "error") == "error"
            }
        )
    )


__all__ = ["inspect_capacity_convergence"]
