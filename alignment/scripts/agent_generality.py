from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.datasets.registry import list_dataset_specs

ROOT = Path(__file__).resolve().parents[1]
COUNTEREXAMPLE_TESTS = ["tests"]
GENERIC_CORE_FILES = [
    "src/metro_alignment/canonical.py",
    "src/metro_alignment/sampling.py",
    "src/metro_alignment/metro_trace.py",
    "src/metro_alignment/metrics/fundamental.py",
    "src/metro_alignment/metrics/comparison.py",
]


def _finding(severity: str, message: str, evidence: str) -> dict[str, str]:
    return {"severity": severity, "message": message, "evidence": evidence}


def _run_counterexamples(findings: list[dict[str, str]]) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *COUNTEREXAMPLE_TESTS, "-q"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-8:])
    if result.returncode:
        findings.append(_finding("P1", "generality counterexample suite failed", tail))
        return []
    return [f"counterexample suite passed: {tail}"]


def _review_core_parameterization(findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    forbidden_dataset_ids = [spec.dataset_id for spec in list_dataset_specs()]
    for relative in GENERIC_CORE_FILES:
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        hits = [dataset_id for dataset_id in forbidden_dataset_ids if dataset_id.lower() in source]
        if hits:
            findings.append(
                _finding(
                    "P1", "generic core contains dataset-ID branch/coupling", f"{relative}: {hits}"
                )
            )
        else:
            evidence.append(f"{relative}: no registered dataset-ID coupling")
    return evidence


def _review_registry(findings: list[dict[str, str]]) -> list[str]:
    active = []
    pending = []
    for spec in list_dataset_specs():
        if not spec.license.strip() or not spec.citation.strip():
            findings.append(_finding("P1", "dataset lacks license/citation", spec.dataset_id))
        if spec.status == "active":
            active.append(spec.dataset_id)
            if not spec.files:
                findings.append(
                    _finding("P1", "active dataset has no file contract", spec.dataset_id)
                )
        else:
            pending.append(spec.dataset_id)
            if not spec.notes.strip():
                findings.append(
                    _finding("P1", "pending dataset lacks explicit reason", spec.dataset_id)
                )
    if not active:
        findings.append(_finding("P0", "no active dataset exercises the generic path", "registry"))
    return [f"active={active}; explicit pending={pending}"]


def _review_sampling_evidence(findings: list[dict[str, str]]) -> list[str]:
    evidence: list[str] = []
    for spec in list_dataset_specs():
        if spec.status != "active":
            continue
        path = ROOT / "data" / "metrics" / f"{spec.dataset_id}_observed.json"
        if not path.exists():
            findings.append(_finding("P1", "real sampling evidence is missing", str(path)))
            continue
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        sampling = payload.get("metadata", {}).get("sampling", {})
        if sampling.get("strategy") != "complete_contiguous_frame_windows":
            evidence.append(f"{spec.dataset_id}: full trajectory metric evaluation")
            continue
        if sampling.get("source_continuity_verified") is not True:
            findings.append(
                _finding(
                    "P1",
                    "sample windows do not prove source-frame and source-time continuity",
                    f"{spec.dataset_id}: {json.dumps(sampling, ensure_ascii=False)}",
                )
            )
        if sampling.get("time_rebased") is not True:
            findings.append(
                _finding(
                    "P1",
                    "disjoint windows can create artificial frame gaps",
                    f"{spec.dataset_id}: {json.dumps(sampling, ensure_ascii=False)}",
                )
            )
        packed = int(sampling.get("packed_frame_count", 0))
        binned = sum(
            int(item.get("n", 0))
            for item in payload.get("metrics", {}).get("fundamental_diagram", {}).get("bins", [])
        )
        if packed <= 0 or binned > packed:
            findings.append(
                _finding(
                    "P1",
                    "sampled FD support exceeds real sampled frames",
                    f"{spec.dataset_id}: binned={binned}, packed={packed}",
                )
            )
        evidence.append(
            f"{spec.dataset_id}: window evidence binned_frames={binned}, packed_frames={packed}"
        )
    return evidence


def _review_skip_tests_gate(findings: list[dict[str, str]]) -> list[str]:
    result = subprocess.run(
        [sys.executable, "scripts/verify_acceptance.py", "--skip-tests"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        findings.append(_finding("P1", "skip-tests gate output is unreadable", str(exc)))
        return []
    if result.returncode == 0 or payload.get("implementation_status") == "pass":
        findings.append(_finding("P1", "skip-tests can forge a passing acceptance", str(payload)))
        return []
    return ["skip-tests is fail-closed and cannot create a passing acceptance"]


def run(round_id: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    evidence = _run_counterexamples(findings)
    evidence.extend(_review_core_parameterization(findings))
    evidence.extend(_review_registry(findings))
    evidence.extend(_review_sampling_evidence(findings))
    evidence.extend(_review_skip_tests_gate(findings))
    blockers = [item for item in findings if item["severity"] in {"P0", "P1"}]
    return {
        "round": round_id,
        "agent": "generality_patch_vs_solution",
        "status": "fail" if blockers else "pass",
        "evidence": evidence,
        "findings": findings,
        "scope_statement": (
            "Generic contracts are verified for registered sources and supported trace schemas; "
            "pending datasets/scenes remain explicitly unimplemented, not silently passed."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review fallback patch vs general solution")
    parser.add_argument("--round", type=int, default=1, dest="round_id")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run(args.round_id)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        write_json_atomic(args.out, payload)
    print(text)
    raise SystemExit(0 if payload["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
