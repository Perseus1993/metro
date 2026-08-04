"""PM-033 P1 decision logic and report helpers.

This file stays inside ``experiments/torch_movement_p1`` and only consumes the
experiment-side artifacts. It does not touch Metro default runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .calibration import MultiSeedBudgetCurve, PseudoObservationResult, RealDataResult
from .benchmark import BenchmarkResult


DecisionChoice = Literal["paper-go", "scale-up", "limited-go", "stop"]


@dataclass(frozen=True)
class P1DecisionInput:
    curve: MultiSeedBudgetCurve
    benchmarks: list[BenchmarkResult]
    blocker_pass: bool
    pseudo_fit: PseudoObservationResult | None = None
    real_data: list[RealDataResult] | None = None
    p0_evidence_path: str | None = None
    literature_holdout_baseline: float | None = None
    rp_batch_infra_demand: bool = False
    min_gradient_lookback_budgets: int = 1


@dataclass(frozen=True)
class P1DecisionMetrics:
    budget_ratio_min: float
    budget_budget_min: int | None
    throughput_current: float | None
    throughput_baseline_32x300: float | None
    throughput_gate_ratio: float | None
    p1_real_data_pass: bool | None


@dataclass(frozen=True)
class P1DecisionResult:
    decision: DecisionChoice
    reason: str
    blocker_pass: bool
    metric: P1DecisionMetrics
    paper_go_conditions: dict[str, bool]
    evidence: dict[str, object]


def evaluate_p1_decision(input: P1DecisionInput) -> P1DecisionResult:
    """Evaluate PM-033 四选一决策（paper-go / scale-up / limited-go / stop）。"""
    metrics = P1DecisionMetrics(
        budget_ratio_min=float("inf"),
        budget_budget_min=None,
        throughput_current=_select_throughput_32x300(input.benchmarks),
        throughput_baseline_32x300=_p0_throughput_32x300(input.p0_evidence_path),
        throughput_gate_ratio=None,
        p1_real_data_pass=None,
    )

    if metrics.throughput_baseline_32x300 and metrics.throughput_current is not None:
        metrics = P1DecisionMetrics(
            budget_ratio_min=metrics.budget_ratio_min,
            budget_budget_min=metrics.budget_budget_min,
            throughput_current=metrics.throughput_current,
            throughput_baseline_32x300=metrics.throughput_baseline_32x300,
            throughput_gate_ratio=metrics.throughput_current / metrics.throughput_baseline_32x300,
            p1_real_data_pass=metrics.p1_real_data_pass,
        )

    budget_ratio_min, budget_budget_min = _best_budget_ratio(input.curve)
    metrics = P1DecisionMetrics(
        budget_ratio_min=budget_ratio_min,
        budget_budget_min=budget_budget_min,
        throughput_current=metrics.throughput_current,
        throughput_baseline_32x300=metrics.throughput_baseline_32x300,
        throughput_gate_ratio=metrics.throughput_gate_ratio,
        p1_real_data_pass=metrics.p1_real_data_pass,
    )

    paper_go_conditions = _paper_go_conditions(input, metrics)
    throughput_gate = _throughput_gate_pass(metrics)
    real_data_pass = _real_data_pass(input)
    metrics = P1DecisionMetrics(
        budget_ratio_min=metrics.budget_ratio_min,
        budget_budget_min=metrics.budget_budget_min,
        throughput_current=metrics.throughput_current,
        throughput_baseline_32x300=metrics.throughput_baseline_32x300,
        throughput_gate_ratio=metrics.throughput_gate_ratio,
        p1_real_data_pass=real_data_pass,
    )

    conditions = _condition_board(input, metrics, paper_go_conditions, real_data_pass, throughput_gate)
    if conditions["paper_go"] and conditions["blocker"]:
        decision: DecisionChoice = "paper-go"
        reason = (
            "Synthetic calibration ratio meets <=50%, real-data validation passes the literature bound, "
            "and blocker chain is fully clear."
        )
    elif not conditions["blocker"]:
        decision = "stop"
        reason = "P1 blocker failed (contact/geometry path is not yet trustworthy)."
    elif not conditions["throughput_gate"]:
        decision = "stop"
        reason = "Throughput gate failed: 32×300 does not meet P0 80% lower bound."
    elif conditions["scale_up"]:
        decision = "scale-up"
        reason = "Calibration advantage is not significant, but throughput is healthy and RP sensitivity path requests batch-capability retention."
    else:
        decision = "limited-go"
        reason = "Calibration line is suspended; only throughput-capability path is preserved."

    evidence = {
        "method": "PM-033 P1 四选一判据",
        "paper_go_conditions": paper_go_conditions,
        "throughput_gate_pass": throughput_gate,
        "real_data_pass": real_data_pass,
        "throughput_gate_ratio": metrics.throughput_gate_ratio,
        "throughput_baseline_32x300": metrics.throughput_baseline_32x300,
        "throughput_current_32x300": metrics.throughput_current,
        "budget_ratio_min": metrics.budget_ratio_min,
        "budget_budget_min": metrics.budget_budget_min,
        "pseudo_model_gap": None if input.pseudo_fit is None else input.pseudo_fit.model_gap,
        "pseudo_macro_gap": None if input.pseudo_fit is None else input.pseudo_fit.macro_gap,
        "real_dataset": None if not input.real_data else input.real_data[0].dataset,
    }

    return P1DecisionResult(
        decision=decision,
        reason=reason,
        blocker_pass=input.blocker_pass,
        metric=metrics,
        paper_go_conditions=paper_go_conditions,
        evidence=evidence,
    )


def build_paper_outline() -> dict[str, object]:
    """Return a compact paper-outline skeleton used in P1-08."""
    return {
        "central_claim": (
            "在离散运营边界约束下，可微行人仿真内核在保持吞吐路径可维护的前提下，"
            "是否能以更少预算恢复参数并获得可外推的真实场景校准？"
        ),
        "method_components": [
            "联合接触约束求解（P1-01）",
            "多边形可步行域张量化（P1-02）",
            "统一预算下的梯度/黑箱校准对比（P1-03~04）",
            "JuPedSim 伪观测的模型族差距分离（P1-05）",
            "Jülich 公开轨迹留出验证（P1-06）",
        ],
        "figure_plan": [
            "图1: P1-01/P1-02 blockers 结果（M1~M7 + 多边形薄切片）",
            "图2: 合成多参数预算-误差曲线（autograd vs black-box p50/p95）",
            "图3: 训练-留出轨迹误差与宏观指标对比",
            "图4: 吞吐回归（CPU + CUDA；32×300）",
            "图5: 失败样本与边界条件列表",
        ],
        "related_work_positioning": [
            "可微 ABM（AgentTorch/GradABM）在模型域上，尚未覆盖离散设施边界的行人内核标定。",
            "对比参数搜索基线（MassMotion/Viswalk 思路）强调可解释性强但预算代价高。",
            "本工作将梯度法限定于连续参数（参照 PM-032 §6.4）以对齐离散场景可导约束。",
        ],
        "decision_branches": [
            "paper-go, scale-up, limited-go, stop",
            "对应门控: 块级可行性、合成预算优势、真实留出验收、吞吐回归。",
        ],
    }


def _best_budget_ratio(curve: MultiSeedBudgetCurve) -> tuple[float, int | None]:
    min_ratio = float("inf")
    min_budget: int | None = None
    for budget, ratio in zip(curve.budgets, curve.autograd_to_black_box_ratio):
        if ratio < min_ratio:
            min_ratio = ratio
            min_budget = budget
    return min_ratio, min_budget


def _select_throughput_32x300(benchmarks: list[BenchmarkResult]) -> float | None:
    for item in benchmarks:
        if item.device == "cuda" and item.batch_size == 32 and item.capacity == 300:
            return item.agent_steps_per_second
    if benchmarks:
        cuda = [item for item in benchmarks if item.device == "cuda" and item.batch_size == 1 and item.capacity == 300]
        if cuda:
            return cuda[0].agent_steps_per_second
    return None


def _p0_throughput_32x300(path: str | None) -> float | None:
    if path is None:
        package_root = Path(__file__).resolve().parents[2]
        path = str(package_root / "torch_movement_p0" / "evidence" / "p0_evidence.json")
    evidence_path = Path(path)
    if not evidence_path.exists():
        return None
    try:
        import json

        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        for item in payload.get("benchmarks", []):
            if (
                item.get("device") == "cuda"
                and item.get("batch_size") == 32
                and item.get("capacity") == 300
            ):
                return float(item.get("agent_steps_per_second"))
    except Exception:
        return None
    return None


def _throughput_gate_pass(metric: P1DecisionMetrics) -> bool:
    if metric.throughput_current is None:
        return False
    if metric.throughput_baseline_32x300 is None:
        return metric.throughput_current >= 420_000
    return metric.throughput_current >= metric.throughput_baseline_32x300 * 0.8


def _paper_go_conditions(input: P1DecisionInput, metric: P1DecisionMetrics) -> dict[str, bool]:
    gain_condition = metric.budget_ratio_min <= 0.5
    pseudo_ready = input.pseudo_fit is not None and bool(input.pseudo_fit.passed)
    return {
        "blocker_path": input.blocker_pass,
        "gradient_advantage": gain_condition,
        "pseudo_fit_reported": pseudo_ready,
        "minimum_budget_ratio_le_05": gain_condition,
        "minimum_budget_budget_available": metric.budget_budget_min is not None,
    }


def _real_data_pass(input: P1DecisionInput) -> bool | None:
    if input.literature_holdout_baseline is None:
        if not input.real_data:
            return None
        return None
    if not input.real_data:
        return False
    return all(item.holdout_loss <= input.literature_holdout_baseline for item in input.real_data)


def _condition_board(
    input: P1DecisionInput,
    metric: P1DecisionMetrics,
    paper_go_conditions: dict[str, bool],
    real_data_pass: bool | None,
    throughput_gate: bool,
) -> dict[str, bool]:
    blocker = input.blocker_pass and paper_go_conditions["blocker_path"]
    pseudo_ready = paper_go_conditions["pseudo_fit_reported"]
    significant_advantage = paper_go_conditions["minimum_budget_ratio_le_05"]
    return {
        "blocker": blocker,
        "paper_go": blocker and significant_advantage and real_data_pass is True,
        "scale_up": (
            blocker
            and throughput_gate
            and (not significant_advantage)
            and (pseudo_ready or bool(input.real_data))
            and input.rp_batch_infra_demand
        ),
        "throughput_gate": throughput_gate,
        "pseudo_ready": pseudo_ready,
    }
