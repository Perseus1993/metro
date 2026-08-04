from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


JUPEDSIM_BACKENDS = frozenset({"jupedsim", "batched_jupedsim", "micro_jupedsim"})


@dataclass(frozen=True)
class ProductionAcceptancePolicy:
    """Configuration requirements for a production acceptance run."""

    require_validated_calibration: bool = True
    require_physical_clock: bool = True
    require_active_goal_graph: bool = True
    require_strict_jupedsim: bool = True
    require_station_design: bool = True
    require_clearance_window: bool = True


@dataclass(frozen=True)
class AcceptanceIssue:
    code: str
    message: str


@dataclass(frozen=True)
class AcceptanceDecision:
    issues: tuple[AcceptanceIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.issues

    @property
    def status(self) -> str:
        return "pass" if self.passed else "fail"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "issues": [asdict(issue) for issue in self.issues],
        }


def assess_production_scenario(
    scenario: StationSandboxScenario,
    policy: ProductionAcceptancePolicy | None = None,
) -> AcceptanceDecision:
    active_policy = policy or ProductionAcceptancePolicy()
    issues: list[AcceptanceIssue] = []

    if active_policy.require_validated_calibration and not scenario.calibration_profile.research_ready:
        issues.append(
            AcceptanceIssue(
                "calibration.not_validated",
                "production acceptance requires an independently validated calibration profile",
            )
        )
    if active_policy.require_physical_clock and scenario.simulation_clock_mode != "physical":
        issues.append(
            AcceptanceIssue(
                "clock.not_physical",
                "production acceptance requires simulation_clock_mode='physical'",
            )
        )
    if active_policy.require_active_goal_graph and scenario.goal_graph_mode != "active":
        issues.append(
            AcceptanceIssue(
                "planning.not_active",
                "production acceptance requires goal_graph_mode='active'",
            )
        )
    if active_policy.require_strict_jupedsim:
        if scenario.movement_backend_name not in JUPEDSIM_BACKENDS:
            issues.append(
                AcceptanceIssue(
                    "movement.not_jupedsim",
                    "production acceptance requires a JuPedSim movement backend",
                )
            )
        if not scenario.jupedsim_strict:
            issues.append(
                AcceptanceIssue(
                    "movement.not_strict",
                    "production acceptance forbids silent movement fallback",
                )
            )
    if active_policy.require_station_design and scenario.station_design is None:
        issues.append(
            AcceptanceIssue(
                "design.missing",
                "production acceptance requires an explicit station design",
            )
        )
    if active_policy.require_clearance_window and scenario.clearance_minutes <= 0:
        issues.append(
            AcceptanceIssue(
                "horizon.no_clearance_window",
                "production acceptance requires demand to stop before the simulation horizon",
            )
        )
    if scenario.elevator_min_dispatch_persons > scenario.elevator_cabin_capacity_persons:
        issues.append(
            AcceptanceIssue(
                "facility.elevator_dispatch_exceeds_capacity",
                "elevator_min_dispatch_persons must not exceed cabin capacity in production",
            )
        )
    if scenario.train_dwell_seconds > scenario.train_headway_seconds:
        issues.append(
            AcceptanceIssue(
                "train.dwell_exceeds_headway",
                "train_dwell_seconds must not exceed train_headway_seconds in production",
            )
        )
    return AcceptanceDecision(tuple(issues))


def assess_experiment_results(
    results: Iterable[Any],
    *,
    fail_on_warning: bool = False,
) -> AcceptanceDecision:
    issues: list[AcceptanceIssue] = []
    for result in results:
        case_id = str(getattr(getattr(result, "case", None), "case_id", "unknown"))
        if getattr(result, "status", None) != "ok":
            error = getattr(result, "error", None) or "experiment execution failed"
            issues.append(AcceptanceIssue(f"case.{case_id}.execution", str(error)))
            continue

        report = getattr(result, "trajectory_report", None)
        if report is None:
            issues.append(
                AcceptanceIssue(
                    f"case.{case_id}.diagnosis_missing",
                    "successful experiment did not produce a trajectory diagnosis",
                )
            )
            continue

        verdict = getattr(report, "pass_fail", None)
        if verdict == "fail" or (fail_on_warning and verdict == "warn"):
            details = "; ".join(str(item) for item in getattr(report, "issues", ()))
            issues.append(
                AcceptanceIssue(
                    f"case.{case_id}.trajectory_{verdict}",
                    details or f"trajectory diagnosis returned {verdict}",
                )
            )
        elif verdict not in {"pass", "warn"}:
            issues.append(
                AcceptanceIssue(
                    f"case.{case_id}.diagnosis_invalid",
                    f"unknown trajectory verdict: {verdict!r}",
                )
            )
    return AcceptanceDecision(tuple(issues))


def experiment_exit_code(results: Iterable[Any], *, fail_on_warning: bool = False) -> int:
    return 0 if assess_experiment_results(results, fail_on_warning=fail_on_warning).passed else 1
