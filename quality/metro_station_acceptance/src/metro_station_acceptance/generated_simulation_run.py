from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station.adapters.simulation.runtime.walking_cost_accounting import (
    WALKING_COST_SOURCE_NAMES,
)
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout

from .generated_trajectory_gate import evaluate_generated_trajectory_gates
from .goal_graph_acceptance import GoalGraphAcceptanceReport, run_goal_graph_acceptance
from .goal_journey_acceptance import FourJourneyAcceptanceReport, run_four_journey_acceptance
from .operational_acceptance_matrix import (
    OperationalAcceptanceMatrix,
    run_operational_acceptance_matrix,
)
from .operational_acceptance_scenarios import (
    CONGESTED,
    FACILITY_CLOSURE_RECOVERY,
    SINGLE_FACILITY,
    TRAIN_FULL_RECOVERY,
    TRAIN_OUTAGE_RECOVERY,
)


OPERATION_SCENARIO_BY_PROFILE = {
    "normal": SINGLE_FACILITY,
    "congested": CONGESTED,
    "facility_closure": FACILITY_CLOSURE_RECOVERY,
    "train_full": TRAIN_FULL_RECOVERY,
    "train_outage": TRAIN_OUTAGE_RECOVERY,
}


@dataclass(frozen=True)
class GeneratedSimulationRecord:
    recipe_id: str
    operation_profile: str
    operation_scenario_id: str
    journeys: FourJourneyAcceptanceReport | None
    operations: OperationalAcceptanceMatrix | None
    determinism_fingerprint: str | None
    trajectory_gates: dict[str, Any] | None
    blind_trajectory_observation_count: int
    error: str | None
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    @property
    def trajectory_scientific_status(self) -> str:
        if self.trajectory_gates is None:
            return "fail"
        return str(self.trajectory_gates.get("status", "fail"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recipe_id": self.recipe_id,
            "operation_profile": self.operation_profile,
            "operation_scenario_id": self.operation_scenario_id,
            "journeys": None if self.journeys is None else self.journeys.as_dict(),
            "operations": None if self.operations is None else self.operations.as_dict(),
            "determinism_fingerprint": self.determinism_fingerprint,
            "trajectory_gates": self.trajectory_gates,
            "trajectory_scientific_status": self.trajectory_scientific_status,
            "blind_trajectory_observation_count": self.blind_trajectory_observation_count,
            "error": self.error,
            "checks": self.checks,
        }


def run_generated_recipe_simulation(
    recipe: LayoutRecipe,
    seeds: tuple[int, ...],
    normal_options: dict[str, int],
    evacuation_persons: int,
    evacuation_minutes: int,
    include_operations: bool,
    movement_backend_factory: Callable[[], MovementBackend] | None,
) -> GeneratedSimulationRecord:
    scenario_id = OPERATION_SCENARIO_BY_PROFILE[recipe.operation_profile]
    try:
        document = generate_layout(recipe)
        scientific_trajectory_applicable = movement_backend_factory is None
        normal_run_options = dict(normal_options)
        if scientific_trajectory_applicable:
            normal_run_options["tick_seconds"] = 1
        normal_evidence: dict[int, dict[str, Any]] = {}
        journeys = run_four_journey_acceptance(
            layout_id=recipe.recipe_id,
            seeds=seeds,
            movement_backend_factory=movement_backend_factory,
            normal_options=normal_run_options,
            evacuation_persons=evacuation_persons,
            evacuation_minutes=evacuation_minutes,
            station_design=document,
            trajectory_evidence_by_seed=(
                normal_evidence if scientific_trajectory_applicable else None
            ),
        )
        replay = run_goal_graph_acceptance(
            layout_id=recipe.recipe_id,
            seed=seeds[0],
            movement_backend=_backend(movement_backend_factory),
            station_design=document,
            entry_count_hour=normal_options["entry_count_hour"],
            exit_count_hour=normal_options["exit_count_hour"],
            transfer_count_hour=normal_options["transfer_count_hour"],
            demand_minutes=normal_options["demand_minutes"],
            clearance_minutes=normal_options["clearance_minutes"],
            tick_seconds=1 if scientific_trajectory_applicable else 5,
        )
        operations = None
        operational_evidence: dict[tuple[str, int], dict[str, Any]] = {}
        if include_operations:
            operations = run_operational_acceptance_matrix(
                layout_id=recipe.recipe_id,
                seeds=seeds,
                scenario_ids=(scenario_id,),
                movement_backend_factory=movement_backend_factory,
                station_design=document,
                trajectory_evidence_by_case=(
                    operational_evidence if scientific_trajectory_applicable else None
                ),
                tick_seconds=1 if scientific_trajectory_applicable else 5,
            )
        trajectory_gates = evaluate_generated_trajectory_gates(
            seeds=seeds,
            normal_evidence=normal_evidence,
            operational_evidence=operational_evidence,
            operational_scenario_id=scenario_id if include_operations else None,
            applicable=scientific_trajectory_applicable,
            not_applicable_reason=(
                None
                if scientific_trajectory_applicable
                else "custom_movement_backend_factory"
            ),
        )
        fingerprint = _fingerprint(journeys.normal[0])
        checks = {
            "four_journeys_pass": journeys.status == "ok",
            "deterministic_replay": fingerprint == _fingerprint(replay),
            "walking_cost_counts_conserved": sum(
                replay.walking_cost_source_counts.values()
            )
            == replay.walking_cost_evaluation_count,
            "walking_cost_sources_closed_vocabulary": set(
                replay.walking_cost_source_counts
            )
            <= WALKING_COST_SOURCE_NAMES,
            "walking_cost_euclidean_fallback_zero": replay.walking_cost_source_counts.get(
                "euclidean_fallback", 0
            )
            == 0,
            "walking_cost_provider_missing_zero": replay.walking_cost_source_counts.get(
                "provider_missing", 0
            )
            == 0,
            "walking_cost_physical_unreachable_zero": replay.walking_cost_source_counts.get(
                "physical_route_unreachable", 0
            )
            == 0,
            "walking_cost_physical_error_zero": replay.walking_cost_source_counts.get(
                "physical_route_error", 0
            )
            == 0,
            "walking_cost_physical_geodesic_exercised": replay.walking_cost_source_counts.get(
                "physical_waypoint_geodesic", 0
            )
            > 0,
        }
        if scientific_trajectory_applicable:
            checks["trajectory_all_required_cases_evaluated"] = (
                trajectory_gates["evaluated_case_count"]
                == trajectory_gates["required_case_count"]
            )
            checks["trajectory_scientific_gate_pass"] = (
                trajectory_gates["status"] == "pass"
                and trajectory_gates["scientific_pass"] is True
            )
        else:
            checks["trajectory_not_applicable_explicit"] = (
                trajectory_gates["status"] == "not_applicable"
                and trajectory_gates["scientific_pass"] is None
            )
        if include_operations:
            checks["operation_profile_pass"] = operations is not None and operations.status == "ok"
        return GeneratedSimulationRecord(
            recipe.recipe_id,
            recipe.operation_profile,
            scenario_id,
            journeys,
            operations,
            fingerprint,
            trajectory_gates,
            int(trajectory_gates["blind_observation_count"]),
            None,
            checks,
        )
    except Exception as exc:
        return GeneratedSimulationRecord(
            recipe.recipe_id,
            recipe.operation_profile,
            scenario_id,
            None,
            None,
            None,
            None,
            0,
            f"{type(exc).__name__}: {exc}",
            {"simulation_completed": False},
        )


def _fingerprint(report: GoalGraphAcceptanceReport) -> str:
    payload = asdict(report)
    payload.pop("wall_seconds", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _backend(
    factory: Callable[[], MovementBackend] | None,
) -> MovementBackend | None:
    return None if factory is None else factory()
