from __future__ import annotations

import hashlib
import json
from itertools import product

from .demand_fault_designs import TOPOLOGY_BASES
from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


DEMAND_FAULT_GENERATOR_VERSION = "demand_fault_trial.v1"
DEMAND_PROFILES = ("D1-SKEW", "D2-COUNTER", "D3-PULSE")
FAULT_PROFILES = (
    "F1-ELEVATOR",
    "F2-STAIRS",
    "F3-ESCALATOR",
    "F4-GATE",
    "F5A-TRAIN-FULL",
    "F5B-TRAIN-OUTAGE",
)
SEEDS = (41, 42, 43)


def demand_fault_cases() -> tuple[LayoutExplorationCase, ...]:
    cases: list[LayoutExplorationCase] = []
    for topology, demand, seed in product(TOPOLOGY_BASES, DEMAND_PROFILES, SEEDS):
        baseline_id = _case_id(topology, demand, "BASELINE", seed)
        pairing = pairing_fingerprint(topology, demand, seed)
        cases.append(_case(baseline_id, topology, demand, "BASELINE", seed, pairing, baseline_id))
        for fault in FAULT_PROFILES:
            cases.append(
                _case(
                    _case_id(topology, demand, fault, seed),
                    topology,
                    demand,
                    fault,
                    seed,
                    pairing,
                    baseline_id,
                )
            )
    result = tuple(cases)
    validate_case_catalog(result)
    return result


def demand_fault_config_counts(cases: tuple[LayoutExplorationCase, ...]) -> dict[str, int]:
    baseline = {
        (case.factors["topology"], case.factors["demand"])
        for case in cases
        if case.factors["fault"] == "BASELINE"
    }
    faults = {
        (case.factors["topology"], case.factors["demand"], case.factors["fault"])
        for case in cases
        if case.factors["fault"] != "BASELINE"
    }
    return {"baseline_configs": len(baseline), "fault_configs": len(faults), "runs": len(cases)}


def pairing_fingerprint(topology: str, demand: str, seed: int) -> str:
    payload = json.dumps(
        {"topology": topology, "demand": demand, "seed": seed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _case(
    case_id: str,
    topology: str,
    demand: str,
    fault: str,
    seed: int,
    pairing: str,
    baseline_id: str,
) -> LayoutExplorationCase:
    return LayoutExplorationCase(
        suite_id="PM028-E3",
        case_id=case_id,
        generator_version=DEMAND_FAULT_GENERATOR_VERSION,
        expected_class="VALID",
        factors={
            "topology": topology,
            "demand": demand,
            "fault": fault,
            "baseline_case_id": baseline_id,
            "pairing_fingerprint": pairing,
        },
        seed=seed,
    )


def _case_id(topology: str, demand: str, fault: str, seed: int) -> str:
    return f"E3-{topology}-{demand}-{fault}-S{seed}"
