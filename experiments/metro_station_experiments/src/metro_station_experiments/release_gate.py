from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def assess_release(
    *,
    emergency: Mapping[str, Any],
    reliability_reports: Iterable[Mapping[str, Any]],
    sensitivity: Mapping[str, Any],
    performance: Mapping[str, Any],
    calibration: Mapping[str, Any],
    required_populations: Sequence[int] = (60, 120, 240),
    minimum_reliability_samples: int = 30,
    density_threshold_authority_approved: bool = False,
    expected_model_evidence_version: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    _model_version_check(
        "emergency_matrix",
        emergency.get("metadata", {}).get("model_evidence_version"),
        expected_model_evidence_version,
        blockers,
        checks,
    )
    _emergency_check(emergency, blockers, checks)
    reliability_reports = list(reliability_reports)
    valid_reliability_reports = [
        report
        for report in reliability_reports
        if expected_model_evidence_version is None
        or report.get("model_evidence_version") == expected_model_evidence_version
    ]
    for report in reliability_reports:
        _model_version_check(
            "reliability",
            report.get("model_evidence_version"),
            expected_model_evidence_version,
            blockers,
            checks,
        )
    _reliability_check(
        valid_reliability_reports,
        required_populations,
        minimum_reliability_samples,
        blockers,
        checks,
    )
    for name, payload in (("sensitivity", sensitivity), ("performance", performance)):
        _model_version_check(
            name,
            payload.get("model_evidence_version"),
            expected_model_evidence_version,
            blockers,
            checks,
        )
        _component_check(name, payload, blockers, checks)
    _component_check("calibration", calibration, blockers, checks)
    authority_status = "pass" if density_threshold_authority_approved else "blocked"
    checks.append({"component": "density_threshold_authority", "status": authority_status})
    if not density_threshold_authority_approved:
        blockers.append(
            {
                "code": "safety.density_threshold_not_approved",
                "message": "6.0 persons/m2 candidate threshold lacks operator/fire authority approval",
            }
        )
    return {
        "status": "blocked" if blockers else "pass",
        "production_ready": not blockers,
        "checks": checks,
        "blocker_count": len(blockers),
        "blockers": blockers,
    }


def _model_version_check(
    component: str,
    actual: Any,
    expected: str | None,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    if expected is None:
        return
    status = "pass" if actual == expected else "stale"
    checks.append({"component": f"{component}_model_version", "status": status})
    if status == "pass":
        return
    blockers.append(
        {
            "code": "evidence.model_version_mismatch",
            "component": component,
            "actual": actual,
            "expected": expected,
        }
    )


def _emergency_check(
    payload: Mapping[str, Any],
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    summary = payload.get("summary", {})
    failed = int(summary.get("errors", 0) or 0) + int(summary.get("acceptance_failed", 0) or 0)
    runs = int(summary.get("runs", 0) or 0)
    status = "pass" if runs > 0 and failed == 0 else "fail"
    checks.append({"component": "emergency_matrix", "status": status, "runs": runs})
    if status != "pass":
        blockers.append(
            {
                "code": "emergency.matrix_failed",
                "message": f"emergency matrix has {failed} failed/error runs out of {runs}",
            }
        )


def _reliability_check(
    reports: Iterable[Mapping[str, Any]],
    required_populations: Sequence[int],
    minimum_samples: int,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    best: dict[int, Mapping[str, Any]] = {}
    for report in reports:
        for group in report.get("groups", []):
            population = int(group.get("population", 0) or 0)
            if population not in best or int(group.get("sample_count", 0) or 0) > int(
                best[population].get("sample_count", 0) or 0
            ):
                best[population] = group
    for population in required_populations:
        group = best.get(population, {})
        count = int(group.get("sample_count", 0) or 0)
        failures = int(group.get("execution_failures", 0) or 0) + int(
            group.get("acceptance_failures", 0) or 0
        )
        status = "pass" if count >= minimum_samples and failures == 0 else "blocked"
        checks.append(
            {
                "component": "reliability",
                "population": population,
                "status": status,
                "sample_count": count,
            }
        )
        if count < minimum_samples:
            blockers.append(
                {
                    "code": "reliability.insufficient_samples",
                    "population": population,
                    "actual": count,
                    "required": minimum_samples,
                }
            )
        if failures:
            blockers.append(
                {
                    "code": "reliability.failures_observed",
                    "population": population,
                    "failures": failures,
                }
            )


def _component_check(
    name: str,
    payload: Mapping[str, Any],
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    component = _component_payload(name, payload)
    status = str(component.get("status", "missing"))
    checks.append({"component": name, "status": status})
    if status == "pass":
        return
    issues = component.get("issues") or component.get("inert_parameters") or []
    if not issues:
        issues = [{"code": f"{name}.not_passed", "message": f"{name} status is {status}"}]
    for issue in issues:
        normalized = dict(issue)
        if "code" not in normalized and "issue" in normalized:
            normalized["code"] = normalized.pop("issue")
        blockers.append({"component": name, **normalized})


def _component_payload(name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if name == "sensitivity" and isinstance(payload.get("report"), Mapping):
        return payload["report"]
    if name == "performance" and isinstance(payload.get("decision"), Mapping):
        return payload["decision"]
    return payload
