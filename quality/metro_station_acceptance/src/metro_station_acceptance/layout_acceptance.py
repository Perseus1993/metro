"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from .goal_graph_acceptance import GoalGraphAcceptanceReport, run_goal_graph_acceptance
from .goal_journey_acceptance import FourJourneyAcceptanceReport, run_four_journey_acceptance
from .layout_acceptance_contract import (
    LAYOUT_IDS,
    LayoutContractReport,
    inspect_layout_contract,
)
from .operational_acceptance_matrix import (
    OperationalAcceptanceMatrix,
    run_operational_acceptance_matrix,
)
from .operational_acceptance_scenarios import OPERATIONAL_SCENARIOS


@dataclass(frozen=True)
class AcceptanceTierProfile:
    tier: str
    seeds: tuple[int, ...]
    normal_options: dict[str, int]
    evacuation_persons: int
    evacuation_minutes: int
    max_normal_wall_seconds: float


@dataclass(frozen=True)
class LayoutMaturityReport:
    layout_id: str
    contract: LayoutContractReport
    journeys: FourJourneyAcceptanceReport
    operations: OperationalAcceptanceMatrix
    determinism_fingerprint: str
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "layout_id": self.layout_id,
            "contract": self.contract.as_dict(),
            "journeys": self.journeys.as_dict(),
            "operations": self.operations.as_dict(),
            "determinism_fingerprint": self.determinism_fingerprint,
            "checks": self.checks,
        }


@dataclass(frozen=True)
class CrossLayoutAcceptanceReport:
    tier: str
    layout_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    layouts: tuple[LayoutMaturityReport, ...]
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "layout_acceptance.v1",
            "status": self.status,
            "tier": self.tier,
            "layout_ids": self.layout_ids,
            "seeds": self.seeds,
            "layouts": [report.as_dict() for report in self.layouts],
            "checks": self.checks,
        }


def acceptance_tier_profile(tier: str) -> AcceptanceTierProfile:
    profiles = {
        "smoke": AcceptanceTierProfile(
            tier="smoke",
            seeds=(42,),
            normal_options=_normal_options(120, 120, 120, 2, 25),
            evacuation_persons=12,
            evacuation_minutes=8,
            max_normal_wall_seconds=60.0,
        ),
        "nightly": AcceptanceTierProfile(
            tier="nightly",
            seeds=(41, 42, 43),
            normal_options=_normal_options(600, 300, 300, 3, 17),
            evacuation_persons=20,
            evacuation_minutes=6,
            max_normal_wall_seconds=180.0,
        ),
        "release": AcceptanceTierProfile(
            tier="release",
            seeds=(41, 42, 43),
            normal_options=_normal_options(1800, 900, 900, 5, 25),
            evacuation_persons=30,
            evacuation_minutes=8,
            max_normal_wall_seconds=300.0,
        ),
    }
    try:
        return profiles[tier]
    except KeyError as exc:
        raise ValueError("acceptance tier must be smoke, nightly, or release") from exc


def run_cross_layout_acceptance(
    *,
    tier: str = "smoke",
    layout_ids: tuple[str, ...] = LAYOUT_IDS,
    seeds: tuple[int, ...] | None = None,
    movement_backend_factory: Callable[[], MovementBackend] | None = None,
) -> CrossLayoutAcceptanceReport:
    profile = acceptance_tier_profile(tier)
    selected_seeds = profile.seeds if seeds is None else seeds
    _validate_matrix(layout_ids, selected_seeds)
    layouts = tuple(
        _run_layout(
            layout_id,
            profile,
            selected_seeds,
            movement_backend_factory,
        )
        for layout_id in layout_ids
    )
    shared_check_names = {
        tuple(report.checks) for report in layouts
    }
    checks = {
        "all_requested_layouts_reported": tuple(report.layout_id for report in layouts)
        == layout_ids,
        "all_layouts_mature": bool(layouts)
        and all(report.status == "ok" for report in layouts),
        "same_maturity_contract": len(shared_check_names) == 1,
        "journey_matrix_complete": all(
            len(report.journeys.normal) == len(selected_seeds)
            and len(report.journeys.evacuation) == len(selected_seeds)
            for report in layouts
        ),
        "operational_matrix_complete": all(
            len(report.operations.reports)
            == len(selected_seeds) * len(OPERATIONAL_SCENARIOS)
            for report in layouts
        ),
    }
    return CrossLayoutAcceptanceReport(
        tier=tier,
        layout_ids=layout_ids,
        seeds=selected_seeds,
        layouts=layouts,
        checks=checks,
    )


def _run_layout(
    layout_id: str,
    profile: AcceptanceTierProfile,
    seeds: tuple[int, ...],
    movement_backend_factory: Callable[[], MovementBackend] | None,
) -> LayoutMaturityReport:
    contract = inspect_layout_contract(layout_id)
    journeys = run_four_journey_acceptance(
        layout_id=layout_id,
        seeds=seeds,
        movement_backend_factory=movement_backend_factory,
        normal_options=profile.normal_options,
        evacuation_persons=profile.evacuation_persons,
        evacuation_minutes=profile.evacuation_minutes,
    )
    operations = run_operational_acceptance_matrix(
        layout_id=layout_id,
        seeds=seeds,
        movement_backend_factory=movement_backend_factory,
    )
    replay = run_goal_graph_acceptance(
        layout_id=layout_id,
        seed=seeds[0],
        movement_backend=_backend(movement_backend_factory),
        **profile.normal_options,
    )
    expected_fingerprint = _normal_fingerprint(journeys.normal[0])
    replay_fingerprint = _normal_fingerprint(replay)
    checks = {
        "topology_contract_pass": contract.status == "ok",
        "four_journeys_pass": journeys.status == "ok",
        "operational_recovery_pass": operations.status == "ok",
        "deterministic_replay": expected_fingerprint == replay_fingerprint,
        "strict_clearance_all_runs": _strict_clearance(journeys, operations),
        "multi_passenger_trajectory_evidence": _multi_passenger_evidence(journeys),
        "normal_runtime_within_budget": all(
            report.wall_seconds <= profile.max_normal_wall_seconds
            for report in journeys.normal
        ),
    }
    return LayoutMaturityReport(
        layout_id=layout_id,
        contract=contract,
        journeys=journeys,
        operations=operations,
        determinism_fingerprint=expected_fingerprint,
        checks=checks,
    )


def _normal_fingerprint(report: GoalGraphAcceptanceReport) -> str:
    payload = asdict(report)
    payload.pop("wall_seconds", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _strict_clearance(
    journeys: FourJourneyAcceptanceReport,
    operations: OperationalAcceptanceMatrix,
) -> bool:
    journey_reports = (*journeys.normal, *journeys.evacuation)
    return all(not report.clearance_blocker_codes for report in journey_reports) and all(
        not report.clearance_blocker_codes for report in operations.reports
    )


def _multi_passenger_evidence(journeys: FourJourneyAcceptanceReport) -> bool:
    return all(
        report.spawned_persons >= 12
        and report.trajectory_count == report.graph_runtime_count
        for report in journeys.normal
    ) and all(
        report.spawned_persons >= 12
        and report.trajectory_count == report.graph_runtimes
        for report in journeys.evacuation
    )


def _normal_options(
    entry_count_hour: int,
    exit_count_hour: int,
    transfer_count_hour: int,
    demand_minutes: int,
    clearance_minutes: int,
) -> dict[str, int]:
    return {
        "entry_count_hour": entry_count_hour,
        "exit_count_hour": exit_count_hour,
        "transfer_count_hour": transfer_count_hour,
        "demand_minutes": demand_minutes,
        "clearance_minutes": clearance_minutes,
    }


def _backend(
    factory: Callable[[], MovementBackend] | None,
) -> MovementBackend | None:
    return None if factory is None else factory()


def _validate_matrix(layout_ids: tuple[str, ...], seeds: tuple[int, ...]) -> None:
    if not layout_ids:
        raise ValueError("layout acceptance requires at least one layout")
    unknown = sorted(set(layout_ids) - set(LAYOUT_IDS))
    if unknown:
        raise ValueError(f"unknown layout acceptance templates: {', '.join(unknown)}")
    if len(set(layout_ids)) != len(layout_ids):
        raise ValueError("layout acceptance layouts must be unique")
    if not seeds:
        raise ValueError("layout acceptance requires at least one seed")
