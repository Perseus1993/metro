from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from metro_station.adapters.routing_plugins import (
    BaselineEvacuationRouter,
    run_routing_contract_suite,
)
from metro_station.application.routing_plugins import (
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
    PassengerGroupFacts,
    RoutingDiagnostics,
    RoutingEdge,
    RoutingNode,
    RoutingTopology,
    manifest_from_json,
    manifest_to_json,
    routing_request_from_json,
    routing_request_to_json,
    routing_response_from_json,
    routing_response_to_json,
    validate_routing_response,
)


FIXTURES = Path("tests/fixtures/routing_plugins")
EXAMPLE_MANIFEST = Path("examples/evacuation_routing_plugin/manifest.json")


def _request() -> EvacuationRoutingRequest:
    topology = RoutingTopology(
        "golden-topology",
        (
            RoutingNode("A", "L1", 0.0, 0.0, "zone"),
            RoutingNode("B", "L1", 1.0, 0.0, "exit"),
        ),
        (RoutingEdge("ab", "A", "B", 1.0, "walk"),),
    )
    return EvacuationRoutingRequest(
        "golden-request",
        12.5,
        "A",
        "B",
        (),
        PassengerGroupFacts(2, "evacuate_station"),
        42,
        topology,
        {"cost_multiplier": 1.0},
    )


def _response() -> EvacuationRoutingResponse:
    return EvacuationRoutingResponse(
        "golden-request",
        "success",
        ("A", "B"),
        ("ab",),
        1.0,
        RoutingDiagnostics(2, "route_found", {"source": "golden"}),
    )


def test_manifest_request_and_response_match_v1_golden_files() -> None:
    manifest_source = EXAMPLE_MANIFEST.read_text(encoding="utf-8")
    request_source = (FIXTURES / "request_v1.json").read_text(encoding="utf-8")
    response_source = (FIXTURES / "response_v1.json").read_text(encoding="utf-8")

    assert manifest_to_json(manifest_from_json(manifest_source)) == manifest_source
    assert routing_request_from_json(request_source) == _request()
    assert routing_request_to_json(_request(), indent=2) == request_source
    assert routing_response_from_json(response_source) == _response()
    assert routing_response_to_json(_response(), indent=2) == response_source


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"schema_version": "algorithm-plugin/v2"}, "manifest schema"),
        ({"kind": "movement_model"}, "plugin kind"),
        ({"api_version": "evacuation-routing/v2"}, "routing API"),
        ({"capabilities": ("unknown",)}, "capabilities"),
    ],
)
def test_manifest_rejects_incompatible_versions_and_capabilities(changes, message) -> None:
    manifest = manifest_from_json(EXAMPLE_MANIFEST.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match=message):
        replace(manifest, **changes)


def test_manifest_validates_parameters_with_json_schema() -> None:
    manifest = manifest_from_json(EXAMPLE_MANIFEST.read_text(encoding="utf-8"))

    assert manifest.validate_parameters({"cost_multiplier": 2.0}) == {"cost_multiplier": 2.0}
    with pytest.raises(ValueError, match="cost_multiplier"):
        manifest.validate_parameters({"cost_multiplier": 0})
    with pytest.raises(ValueError, match="Additional properties"):
        manifest.validate_parameters({"other": True})


@pytest.mark.parametrize(
    "response, message",
    [
        (
            EvacuationRoutingResponse(
                "golden-request",
                "success",
                ("A", "X"),
                ("ab",),
                1.0,
                RoutingDiagnostics(1, "bad"),
            ),
            "destination",
        ),
        (
            EvacuationRoutingResponse(
                "golden-request",
                "success",
                ("A", "X", "B"),
                ("ab", "ab"),
                1.0,
                RoutingDiagnostics(1, "bad"),
            ),
            "unknown nodes",
        ),
        (
            EvacuationRoutingResponse(
                "golden-request",
                "success",
                ("A", "B"),
                ("missing",),
                1.0,
                RoutingDiagnostics(1, "bad"),
            ),
            "unknown edges",
        ),
        (
            EvacuationRoutingResponse(
                "golden-request",
                "no_route",
                ("A",),
                (),
                None,
                RoutingDiagnostics(1, "bad"),
            ),
            "empty paths",
        ),
    ],
)
def test_response_validation_rejects_illegal_paths(response, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_routing_response(_request(), response)


def test_response_rejects_non_finite_cost_and_missing_diagnostics() -> None:
    with pytest.raises(ValueError, match="finite"):
        replace(_response(), cost=float("nan"))
    payload = _response().as_dict()
    payload.pop("diagnostics")
    with pytest.raises(ValueError, match="missing diagnostics"):
        EvacuationRoutingResponse.from_dict(payload)


def test_request_rejects_a_tampered_topology_fingerprint() -> None:
    payload = _request().as_dict()
    payload["topology"]["edges"][0]["cost"] = 9.0

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        EvacuationRoutingRequest.from_dict(payload)


def test_response_validation_rejects_a_closed_edge() -> None:
    request = replace(_request(), closed_edge_ids=("ab",))

    with pytest.raises(ValueError, match="closed edge"):
        validate_routing_response(request, _response())


def test_builtin_baseline_passes_all_ten_contract_cases() -> None:
    report = run_routing_contract_suite(BaselineEvacuationRouter())

    assert report.passed
    assert len(report.cases) == 10
    assert report.active_processes_after == 0
