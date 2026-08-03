from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .trajectory_truth_colocation import persistent_exact_colocations
from .trajectory_truth_inputs import extract_truth_input
from .trajectory_truth_series import (
    excessive_average_speeds,
    non_finite_observations,
    observations_by_agent,
    same_time_position_conflicts,
    sampling_interval_distribution,
    time_regressions,
)


TRAJECTORY_TRUTH_GATE_SCHEMA_VERSION = "trajectory_truth_gate_report.v1"


@dataclass(frozen=True)
class TrajectoryTruthGateConfig:
    max_average_speed_m_s: float = 3.5
    same_time_position_epsilon: float = 0.001
    time_epsilon_s: float = 1e-9
    min_exact_colocation_duration_s: float = 2.0
    min_exact_colocation_samples: int = 2
    max_issue_examples: int = 20
    coordinate_unit: str | None = None

    def validate(self) -> None:
        positive = {
            "max_average_speed_m_s": self.max_average_speed_m_s,
            "max_issue_examples": self.max_issue_examples,
            "min_exact_colocation_samples": self.min_exact_colocation_samples,
        }
        if any(value <= 0 for value in positive.values()):
            raise ValueError("speed, sample count, and example count must be positive")
        if self.min_exact_colocation_samples < 2:
            raise ValueError("min_exact_colocation_samples must be at least 2")
        if min(
            self.same_time_position_epsilon,
            self.time_epsilon_s,
            self.min_exact_colocation_duration_s,
        ) < 0:
            raise ValueError("epsilons and colocation duration must not be negative")


def analyze_trajectory_truth(
    payload: object,
    *,
    config: TrajectoryTruthGateConfig | None = None,
) -> dict[str, Any]:
    """Run structural hard gates over authoritative passenger coordinates."""

    active_config = config or TrajectoryTruthGateConfig()
    active_config.validate()
    truth = extract_truth_input(payload, coordinate_unit=active_config.coordinate_unit)
    by_agent = observations_by_agent(truth.observations)

    non_finite_count, non_finite_examples = non_finite_observations(
        truth.observations,
        max_examples=active_config.max_issue_examples,
    )
    regression_count, regression_examples = time_regressions(
        by_agent,
        time_epsilon_s=active_config.time_epsilon_s,
        max_examples=active_config.max_issue_examples,
    )
    conflict_count, conflict_examples = same_time_position_conflicts(
        truth.observations,
        position_epsilon=active_config.same_time_position_epsilon,
        max_examples=active_config.max_issue_examples,
    )
    colocation_count, colocation_examples = persistent_exact_colocations(
        truth.observations,
        min_duration_s=active_config.min_exact_colocation_duration_s,
        min_samples=active_config.min_exact_colocation_samples,
        max_examples=active_config.max_issue_examples,
    )

    checks = {
        "finite_time_and_coordinates": _hard_check(
            non_finite_count,
            count_unit="observations",
            threshold={"maximum": 0},
            examples=non_finite_examples,
        ),
        "strictly_non_regressing_time": _hard_check(
            regression_count,
            count_unit="segments",
            threshold={"maximum": 0},
            examples=regression_examples,
        ),
        "same_id_same_time_single_position": _hard_check(
            conflict_count,
            count_unit="agent_timestamps",
            threshold={
                "maximum": 0,
                "position_epsilon": active_config.same_time_position_epsilon,
            },
            examples=conflict_examples,
        ),
        "no_persistent_exact_colocation": _hard_check(
            colocation_count,
            count_unit="agent_pair_runs",
            threshold={
                "maximum": 0,
                "minimum_duration_s": active_config.min_exact_colocation_duration_s,
                "minimum_samples": active_config.min_exact_colocation_samples,
            },
            examples=colocation_examples,
        ),
        "average_speed_within_bound": _speed_check(
            truth.coordinate_unit,
            by_agent,
            config=active_config,
        ),
    }
    failed_checks = [name for name, check in checks.items() if check["status"] == "fail"]
    return {
        "schema_version": TRAJECTORY_TRUTH_GATE_SCHEMA_VERSION,
        "status": "pass" if not failed_checks else "fail",
        "passed": not failed_checks,
        "source": {
            "kind": truth.source_kind,
            "coordinate_unit": truth.coordinate_unit,
            "snapshot_count": truth.snapshot_count,
            "observation_count": len(truth.observations),
            "agent_count": len(by_agent),
            "authority": "simulation_truth",
            "visual_samples_accepted": 0,
        },
        "configuration": asdict(active_config),
        "checks": checks,
        "sampling_intervals_s": sampling_interval_distribution(
            by_agent,
            time_epsilon_s=active_config.time_epsilon_s,
        ),
        "summary": {
            "failed_checks": failed_checks,
            "failed_check_count": len(failed_checks),
            "hard_failure_count": sum(
                int(check["count"])
                for check in checks.values()
                if check["status"] == "fail"
            ),
        },
    }


def _speed_check(
    coordinate_unit: str | None,
    by_agent,
    *,
    config: TrajectoryTruthGateConfig,
) -> dict[str, Any]:
    if coordinate_unit != "m":
        return {
            "status": "skipped",
            "hard": True,
            "count": 0,
            "count_unit": "segments",
            "threshold": {"maximum_average_speed_m_s": config.max_average_speed_m_s},
            "reason": "coordinate unit is not known to be meters",
            "examples": [],
            "observed_max_average_speed_m_s": None,
        }
    count, examples, observed_max = excessive_average_speeds(
        by_agent,
        max_speed=config.max_average_speed_m_s,
        time_epsilon_s=config.time_epsilon_s,
        max_examples=config.max_issue_examples,
    )
    result = _hard_check(
        count,
        count_unit="segments",
        threshold={"maximum_average_speed_m_s": config.max_average_speed_m_s},
        examples=examples,
    )
    result["observed_max_average_speed_m_s"] = observed_max
    return result


def _hard_check(
    count: int,
    *,
    count_unit: str,
    threshold: dict[str, object],
    examples: list[dict[str, object]],
) -> dict[str, Any]:
    return {
        "status": "pass" if count == 0 else "fail",
        "hard": True,
        "count": count,
        "count_unit": count_unit,
        "threshold": threshold,
        "examples": examples,
    }
