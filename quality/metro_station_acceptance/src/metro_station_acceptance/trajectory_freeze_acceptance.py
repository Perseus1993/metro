from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .blind_trajectory_export import anonymized_xy_observations
from .generated_trajectory_gate import evaluate_generated_trajectory_gates
from .goal_journey_acceptance import run_evacuation_acceptance
from .operational_acceptance import run_operational_acceptance
from .operational_acceptance_scenarios import CONGESTED
from .presentation_fidelity_gate import analyze_presentation_fidelity


TRAJECTORY_FREEZE_SCHEMA_VERSION = "trajectory_freeze_acceptance.v1"


@dataclass(frozen=True)
class TrajectoryFreezeSpec:
    case_id: str
    run_kind: str
    layout_id: str
    seed: int
    initial_persons: int | None = None
    minutes: int | None = None
    operational_scenario_id: str | None = None


DEFAULT_TRAJECTORY_FREEZE_SPECS = (
    TrajectoryFreezeSpec(
        case_id="evacuation_10",
        run_kind="evacuation",
        layout_id="three_level_transfer",
        seed=7,
        initial_persons=10,
        minutes=12,
    ),
    TrajectoryFreezeSpec(
        case_id="evacuation_50",
        run_kind="evacuation",
        layout_id="three_level_transfer",
        seed=42,
        initial_persons=50,
        minutes=12,
    ),
    TrajectoryFreezeSpec(
        case_id="evacuation_100",
        run_kind="evacuation",
        layout_id="three_level_transfer",
        seed=99,
        initial_persons=100,
        minutes=15,
    ),
    TrajectoryFreezeSpec(
        case_id="complex_operations",
        run_kind="operations",
        layout_id="three_level_transfer",
        seed=99,
        operational_scenario_id=CONGESTED,
    ),
)


def run_trajectory_freeze_acceptance(
    output_dir: Path,
    *,
    specs: tuple[TrajectoryFreezeSpec, ...] = DEFAULT_TRAJECTORY_FREEZE_SPECS,
) -> dict[str, Any]:
    """Create fresh replay, anonymous XY, and gate evidence for the P11 freeze."""

    if not specs:
        raise ValueError("trajectory freeze requires at least one case")
    case_ids = tuple(spec.case_id for spec in specs)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("trajectory freeze case_id values must be unique")

    output_dir.mkdir(parents=True, exist_ok=True)
    records = [_run_case(spec, output_dir) for spec in specs]
    passed = all(record["status"] == "pass" for record in records)
    payload = {
        "schema_version": TRAJECTORY_FREEZE_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "passed": passed,
        "case_count": len(records),
        "required_case_ids": list(case_ids),
        "records": records,
    }
    _write_json(output_dir / "trajectory_freeze_report.json", payload)
    (output_dir / "trajectory_freeze_report.md").write_text(
        render_trajectory_freeze_markdown(payload),
        encoding="utf-8",
    )
    return payload


def _run_case(spec: TrajectoryFreezeSpec, output_dir: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    if spec.run_kind == "evacuation":
        if spec.initial_persons is None or spec.minutes is None:
            raise ValueError(f"{spec.case_id} requires initial_persons and minutes")
        domain_report = run_evacuation_acceptance(
            layout_id=spec.layout_id,
            seed=spec.seed,
            initial_persons=spec.initial_persons,
            minutes=spec.minutes,
            trajectory_evidence=evidence,
        ).as_dict()
    elif spec.run_kind == "operations":
        if spec.operational_scenario_id is None:
            raise ValueError(f"{spec.case_id} requires operational_scenario_id")
        domain_report = run_operational_acceptance(
            spec.operational_scenario_id,
            layout_id=spec.layout_id,
            seed=spec.seed,
            tick_seconds=1,
            trajectory_evidence=evidence,
        ).as_dict()
    else:
        raise ValueError(f"unsupported trajectory freeze run_kind {spec.run_kind!r}")

    scientific = evaluate_generated_trajectory_gates(
        seeds=(spec.seed,),
        normal_evidence={spec.seed: evidence},
        operational_evidence={},
        operational_scenario_id=None,
        applicable=True,
    )
    presentation = analyze_presentation_fidelity(evidence)
    blind = anonymized_xy_observations(evidence)
    replay_path = output_dir / f"{spec.case_id}.replay.json"
    blind_path = output_dir / f"{spec.case_id}.blind_xy.json"
    _write_json(replay_path, evidence)
    _write_json(blind_path, blind)

    scientific_case = scientific["cases"][0]
    passed = (
        domain_report.get("status") == "ok"
        and scientific_case.get("status") == "pass"
        and bool(presentation.get("passed"))
    )
    return {
        "case": asdict(spec),
        "status": "pass" if passed else "fail",
        "passed": passed,
        "domain_report": domain_report,
        "scientific_gates": scientific_case,
        "presentation_fidelity": presentation,
        "blind_observation_count": len(blind),
        "artifacts": {
            "replay": str(replay_path),
            "blind_xy": str(blind_path),
        },
    }


def render_trajectory_freeze_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# P11 trajectory freeze acceptance",
        "",
        f"- Status: **{str(payload['status']).upper()}**",
        f"- Cases: `{payload['case_count']}`",
        "",
        "| Case | Domain | Truth | Kinematics | Composite | Blind | Presentation |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for record in payload["records"]:
        gates = record["scientific_gates"].get("gates") or {}
        lines.append(
            "| {case_id} | {domain} | {truth} | {kinematics} | {composite} | "
            "{blind} | {presentation} |".format(
                case_id=record["case"]["case_id"],
                domain=_mark(record["domain_report"].get("status") == "ok"),
                truth=_gate_mark(gates, "truth"),
                kinematics=_gate_mark(gates, "kinematics"),
                composite=_gate_mark(gates, "composite"),
                blind=_gate_mark(gates, "blind"),
                presentation=_mark(record["presentation_fidelity"].get("passed")),
            )
        )
    return "\n".join(lines) + "\n"


def _gate_mark(gates: Mapping[str, Any], name: str) -> str:
    report = gates.get(name)
    return _mark(isinstance(report, Mapping) and report.get("passed"))


def _mark(value: object) -> str:
    return "PASS" if bool(value) else "FAIL"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
