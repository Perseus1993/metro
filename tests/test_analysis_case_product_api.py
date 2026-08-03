from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from functools import partial
from http.server import ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from time import monotonic, sleep
from urllib.request import Request, urlopen
from zipfile import ZipFile

import pytest

from metro_station.adapters.simulation.design.templates import create_design
from metro_station.application.analysis_cases import clone_analysis_case, create_analysis_case
from metro_station.application.comparisons import (
    AnalystDecision,
    ComparisonRunSpec,
    RunSummary,
    build_comparison_report,
)
from metro_station_designer.analysis_case_api import (
    build_baseline_case,
    build_candidate_case,
)
from metro_station_designer.comparison_jobs import (
    comparison_job_payload,
    record_decision,
    start_comparison_job,
)
from metro_station_designer.comparison_report_export import comparison_report_bundle
from metro_station_designer.control_plan_catalog import build_control_plan_catalog
from metro_station_designer.server import DesignInspectorHandler, ROOT, build_design_payload


def test_product_case_builder_freezes_controls_and_reports_water_barrier_diff() -> None:
    compiled = build_design_payload("single_level_terminal")
    request = {
        "template_id": "single_level_terminal",
        "case_name": "Baseline",
        "seeds": "7,42,99",
        "demand_minutes": 1,
        "horizon_minutes": 5,
        "tick_seconds": 5,
    }
    baseline = build_baseline_case(request, compiled)
    candidate_compiled = deepcopy(compiled)
    candidate_compiled["document"]["elements"].append(_water_barrier_element("terminal_l1"))

    candidate = build_candidate_case(
        {**request, "baseline": baseline.as_dict(), "case_name": "Water barrier"},
        candidate_compiled,
    )

    assert baseline.seeds == (7, 42, 99)
    assert candidate.simulation == baseline.simulation
    assert candidate.parent_case_id == baseline.case_id
    changed = set(candidate.semantic_payload()["design"]["elements"][-1])
    assert {"id", "kind", "geometry"}.issubset(changed)


def test_product_case_builder_normalizes_control_plan_and_rejects_unaligned_schedule() -> None:
    compiled = build_design_payload("single_level_terminal")
    request = {
        "seeds": [7],
        "demand_minutes": 1,
        "horizon_minutes": 2,
        "tick_seconds": 10,
        "control_plan": _control_plan("l1_terminal", end_seconds=30),
    }

    analysis_case = build_baseline_case(request, compiled)

    saved = analysis_case.simulation["control_plan"]
    assert saved["schema_version"] == "control-plan/v1"
    assert saved["semantic_fingerprint"]
    assert saved["events"][1]["at_seconds"] == 30
    request["control_plan"] = _control_plan("l1_terminal", end_seconds=31)
    with pytest.raises(ValueError, match="align with tick_seconds"):
        build_baseline_case(request, compiled)


def test_designer_control_catalog_exposes_seven_types_and_runtime_facility_ids() -> None:
    compiled = build_design_payload("single_level_terminal")
    document = create_design("single_level_terminal")

    catalog = build_control_plan_catalog(document, compiled["operations"])

    assert len(catalog["measure_types"]) == 7
    available = {
        item["kind"] for item in catalog["measure_types"] if item["runtime_status"] == "available"
    }
    assert available == {
        "water_barrier",
        "isolation_barrier",
        "closure_zone",
        "one_way_channel",
        "access_closure",
        "escalator_direction",
        "staff_guidance",
    }
    assert any(item["id"].startswith("entry_gate:") for item in catalog["facility_targets"])


def test_background_job_records_decision_and_exports_self_contained_bundle() -> None:
    baseline = _empty_case()
    candidate = clone_analysis_case(baseline, name="Candidate")
    started = start_comparison_job(
        {"baseline": baseline.as_dict(), "candidate": candidate.as_dict()}
    )
    result = _wait_for_job(started["job_id"])

    assert result["status"] == "done"
    assert result["report"]["status"] == "completed"
    decided = record_decision(
        started["job_id"],
        {"recommendation": "reject", "rationale": "密度收益不足。", "analyst": "QA"},
    )
    assert decided["report"]["decision"]["recommendation"] == "reject"


def test_report_bundle_contains_cases_json_html_boundary_and_decision() -> None:
    baseline = _empty_case()
    candidate = clone_analysis_case(baseline, name="Candidate")
    spec = ComparisonRunSpec.create(baseline, candidate)
    baseline_summary = replace(
        _summary(spec, "baseline"),
        control_events=(
            {
                "event_id": "deploy-a",
                "measure_id": "barrier-a",
                "measure_kind": "water_barrier",
                "action": "deploy",
                "scheduled_seconds": 10,
                "applied_seconds": 10.0,
                "status": "applied",
                "level_id": "terminal_l1",
                "target_id": None,
                "details": {},
            },
        ),
    )
    report = build_comparison_report(
        spec,
        (baseline_summary, _summary(spec, "candidate")),
        decision=AnalystDecision("more_evidence", "需要现场证据。", "QA"),
    )

    with ZipFile(BytesIO(comparison_report_bundle(report))) as archive:
        assert set(archive.namelist()) == {
            "baseline.analysis-case.json",
            "candidate.analysis-case.json",
            "comparison-report.json",
            "decision-report.html",
        }
        html = archive.read("decision-report.html").decode("utf-8")
        payload = json.loads(archive.read("comparison-report.json"))

    assert "需要现场证据" in html
    assert "Internal exploration only" in html
    assert "管控事件" in html
    assert "water_barrier" in html
    assert payload["decision"]["analyst"] == "QA"


def test_uncalibrated_report_rejects_production_ready_claim() -> None:
    baseline = _empty_case()
    candidate = clone_analysis_case(baseline, name="Candidate")
    spec = ComparisonRunSpec.create(baseline, candidate)

    with pytest.raises(ValueError, match="uncalibrated"):
        build_comparison_report(
            spec,
            (_summary(spec, "baseline"), _summary(spec, "candidate")),
            decision=AnalystDecision("adopt", "This design is production ready.", "QA"),
        )


def test_analysis_case_http_create_import_and_diff() -> None:
    handler = partial(DesignInspectorHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        baseline = _post_json(
            f"{base_url}/api/analysis-cases/baseline",
            {
                "template_id": "single_level_terminal",
                "operations": {"entry_count_hour": 0, "exit_count_hour": 0},
                "seeds": [7],
                "demand_minutes": 1,
                "horizon_minutes": 2,
                "tick_seconds": 30,
            },
        )["case"]
        imported = _post_json(f"{base_url}/api/analysis-cases/import", {"case": baseline})["case"]
        candidate = clone_analysis_case(
            create_analysis_case(
                name="temporary",
                design=baseline["design"],
                operations=baseline["operations"],
                simulation=baseline["simulation"],
                seeds=(7,),
            ),
            name="candidate",
        )
        candidate = replace(candidate, parent_case_id=baseline["case_id"])
        diff = _post_json(
            f"{base_url}/api/analysis-cases/diff",
            {"baseline": baseline, "candidate": candidate.as_dict()},
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert imported["semantic_fingerprint"] == baseline["semantic_fingerprint"]
    assert diff == {"differences": []}


def _empty_case():
    return create_analysis_case(
        name="Baseline",
        design=create_design("single_level_terminal").as_dict(),
        operations={"entry_count_hour": 0, "exit_count_hour": 0},
        simulation={"demand_minutes": 1, "horizon_minutes": 2, "tick_seconds": 30},
        seeds=(7,),
    )


def _summary(spec, role: str) -> RunSummary:
    source = spec.baseline if role == "baseline" else spec.candidate
    return RunSummary(
        role=role,
        case_id=source.case_id,
        seed=7,
        status="ok",
        cleared=True,
        right_censored=False,
        clearance_time_s=60,
        remaining_agents=0,
        total_agents=0,
        peak_density_persons_m2=0,
        density_exposure_person_s=0,
        density_duration_above_threshold_s=0,
        max_gate_queue=0,
        max_vertical_queue=0,
        stuck_agents=0,
    )


def _wait_for_job(job_id: str) -> dict:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        payload = comparison_job_payload(job_id)
        if payload and payload["status"] not in {"queued", "running"}:
            return payload
        sleep(0.05)
    raise AssertionError("comparison job did not complete")


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - local test server
        return json.loads(response.read())


def _water_barrier_element(level_id: str) -> dict:
    return {
        "id": "water_barrier_a",
        "kind": "obstacle",
        "level_id": level_id,
        "geometry": {
            "shape": "rect",
            "x_m": 15.0,
            "y_m": 8.25,
            "width_m": 2.0,
            "height_m": 1.5,
            "rotation_deg": 0.0,
            "points_m": [],
        },
        "label": "Water barrier A",
        "role": "obstacle",
        "ports": [],
        "capacity": None,
        "service_rate_per_min": None,
        "direction": None,
        "line_id": None,
        "metadata": {"blocking": True, "visual_kind": "water_barrier"},
    }


def _control_plan(level_id: str, *, end_seconds: int) -> dict:
    return {
        "schema_version": "control-plan/v1",
        "plan_id": "browser-plan",
        "name": "Browser plan",
        "created_at": "2026-07-16T00:00:00+00:00",
        "updated_at": "2026-07-16T00:00:00+00:00",
        "measures": [
            {
                "measure_id": "barrier-a",
                "kind": "water_barrier",
                "label": "Barrier A",
                "target_id": None,
                "level_id": level_id,
                "initially_active": False,
                "parameters": {
                    "geometry": {
                        "shape": "rect",
                        "x_m": 15.0,
                        "y_m": 8.0,
                        "width_m": 2.0,
                        "height_m": 1.0,
                        "rotation_deg": 0.0,
                        "points_m": [],
                    }
                },
                "metadata": {},
            }
        ],
        "events": [
            {
                "event_id": "deploy-a",
                "measure_id": "barrier-a",
                "at_seconds": 0,
                "action": "deploy",
                "parameters": {},
                "metadata": {},
            },
            {
                "event_id": "remove-a",
                "measure_id": "barrier-a",
                "at_seconds": end_seconds,
                "action": "remove",
                "parameters": {},
                "metadata": {},
            },
        ],
        "metadata": {},
    }
