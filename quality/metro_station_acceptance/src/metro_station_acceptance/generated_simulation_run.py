from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout

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
    error: str | None
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recipe_id": self.recipe_id,
            "operation_profile": self.operation_profile,
            "operation_scenario_id": self.operation_scenario_id,
            "journeys": None if self.journeys is None else self.journeys.as_dict(),
            "operations": None if self.operations is None else self.operations.as_dict(),
            "determinism_fingerprint": self.determinism_fingerprint,
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
        journeys = run_four_journey_acceptance(
            layout_id=recipe.recipe_id,
            seeds=seeds,
            movement_backend_factory=movement_backend_factory,
            normal_options=normal_options,
            evacuation_persons=evacuation_persons,
            evacuation_minutes=evacuation_minutes,
            station_design=document,
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
        )
        operations = None
        if include_operations:
            operations = run_operational_acceptance_matrix(
                layout_id=recipe.recipe_id,
                seeds=seeds,
                scenario_ids=(scenario_id,),
                movement_backend_factory=movement_backend_factory,
                station_design=document,
            )
        fingerprint = _fingerprint(journeys.normal[0])
        checks = {
            "four_journeys_pass": journeys.status == "ok",
            "deterministic_replay": fingerprint == _fingerprint(replay),
        }
        if include_operations:
            checks["operation_profile_pass"] = operations is not None and operations.status == "ok"
        return GeneratedSimulationRecord(
            recipe.recipe_id,
            recipe.operation_profile,
            scenario_id,
            journeys,
            operations,
            fingerprint,
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
