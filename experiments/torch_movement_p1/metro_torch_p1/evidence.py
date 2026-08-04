"""Produce PM-033 P1 decision evidence and decision artifacts."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import torch

from .benchmark import run_benchmarks
from .calibration import (
    GradientCompare,
    MultiSeedBudgetCurve,
    run_autograd_gradient_check,
    run_jupedsim_pseudo_fit,
    run_real_data_like_calibration,
    run_synthetic_four_parameter_recovery,
)
from .decision import P1DecisionInput, evaluate_p1_decision, build_paper_outline
from .scenarios import run_validation_scenarios


def generate_evidence(
    output_directory: Path,
    *,
    device: str | None = None,
    pseudo_seed: int = 17,
    synthetic_seeds: list[int] | None = None,
    synthetic_budgets: list[int] | None = None,
    synthetic_steps: int = 64,
    real_budgets: list[int] | None = None,
    real_steps: int = 120,
    real_dataset: str | None = None,
    literature_holdout_baseline: float | None = None,
    rp_batch_infra_demand: bool = False,
) -> tuple[Path, Path, str]:
    """Generate a PM-033 decision bundle for this experiment directory."""
    run_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    scenarios = run_validation_scenarios(run_device)
    gradient = run_autograd_gradient_check(run_device)
    curve = run_synthetic_four_parameter_recovery(
        device=run_device,
        budgets=synthetic_budgets,
        seeds=synthetic_seeds,
        max_steps=synthetic_steps,
    )
    pseudo_fit = run_jupedsim_pseudo_fit(device=run_device, seed=pseudo_seed)
    real_data = run_real_data_like_calibration(
        device=run_device,
        budgets=real_budgets,
        steps=real_steps,
        dataset_path=real_dataset,
    )
    metro_boundary = _run_metro_boundary_smoke(run_device)
    benchmarks = run_benchmarks()

    all_scenarios_pass = all(item.passed for item in scenarios)
    metro_boundary_passed = bool(metro_boundary.get("passed"))
    blocker_pass = all_scenarios_pass and gradient.passed
    decision = evaluate_p1_decision(
        P1DecisionInput(
            curve=curve,
            benchmarks=benchmarks,
            blocker_pass=blocker_pass,
            pseudo_fit=pseudo_fit,
            real_data=real_data,
            literature_holdout_baseline=literature_holdout_baseline,
            rp_batch_infra_demand=rp_batch_infra_demand,
        )
    )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": _environment_payload(run_device),
        "scope": "P1 标定主线验证；JuPedSim 与 metro_station 默认后端不改。",
        "scenarios": [asdict(item) for item in scenarios],
        "gradient_gate": _gradient_to_dict(gradient),
        "synthetic_4param_recovery": _asdict_curve(curve),
        "jupedsim_pseudo_fit": asdict(pseudo_fit),
        "real_data_calibration": [asdict(item) for item in real_data],
        "metro_boundary": metro_boundary,
        "benchmarks": [asdict(item) for item in benchmarks],
        "paper_outline": build_paper_outline(),
        "decision": {
            "verdict": decision.decision,
            "reason": decision.reason,
            "metrics": asdict(decision.metric),
            "evidence": decision.evidence,
            "paper_go_conditions": decision.paper_go_conditions,
            "blocker_pass": decision.blocker_pass,
            "metro_boundary_passed": metro_boundary_passed,
        },
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "p1_evidence.json"
    markdown_path = output_directory / "P1_EVIDENCE.md"
    json_path.write_text(json.dumps(_json_safe(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return json_path, markdown_path, f"{decision.decision}: {decision.reason}"


def _environment_payload(run_device: str) -> dict:
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "run_device": run_device,
    }


def _gradient_to_dict(gradient: GradientCompare) -> dict:
    return {
        "autograd": gradient.autograd,
        "finite_difference_gradient": gradient.finite_difference,
        "relative_gradient_error": gradient.relative_error,
        "recovered_tau": gradient.recovered,
        "passed": gradient.passed,
    }


def _asdict_curve(curve: MultiSeedBudgetCurve) -> dict:
    return {
        "budgets": curve.budgets,
        "autograd_p50_error": curve.p50_error,
        "autograd_p95_error": curve.p95_error,
        "black_box_p50_error": curve.black_box_p50_error,
        "black_box_p95_error": curve.black_box_p95_error,
        "best_autograd": curve.best_recovered,
        "best_black_box": curve.black_box_best,
        "autograd_to_black_box_ratio": curve.autograd_to_black_box_ratio,
    }


def _run_metro_boundary_smoke(device: str) -> dict[str, object]:
    """Run Metro boundary smoke test if Metro is available; otherwise return fallback evidence.

    This keeps `evidence` runnable in isolated environments where `metro_station`
    is not installed while still preserving blocker intent.
    """

    try:
        from .integration import run_metro_boundary_smoke
    except Exception as exc:
        return {
            "injected": False,
            "progressed_m": None,
            "active_slots": 0,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "status": "metro_station_unavailable",
        }

    try:
        return asdict(run_metro_boundary_smoke(device))
    except Exception as exc:
        return {
            "injected": False,
            "progressed_m": None,
            "active_slots": 0,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "status": "runtime_error",
        }


def _markdown(payload: dict) -> str:
    env = payload["environment"]
    decision = payload["decision"]
    metric = decision["metrics"]
    curve = payload["synthetic_4param_recovery"]
    real_data = payload["real_data_calibration"]
    all_scenarios_pass = all(item["passed"] for item in payload["scenarios"])
    gradient_pass = payload["gradient_gate"]["passed"]
    throughput_pass = bool(decision["evidence"].get("throughput_gate_pass"))
    lines = [
        "# PM-033 P1 Evidence",
        "",
        f"- 生成时间 (UTC): {payload['generated_at_utc']}",
        f"- 环境: Python {env['python']}; Torch {env['torch']}; CUDA {env['cuda_runtime']}; device {env['device']}",
        f"- 决策: **{decision['verdict'].upper()}**",
        f"- 原因: {decision['reason']}",
        "",
        "## 门控汇总",
        f"- 场景门: {'PASS' if all_scenarios_pass else 'FAIL'}",
        f"- 梯度门: {'PASS' if gradient_pass else 'FAIL'}",
        f"- Metro boundary smoke: {'PASS' if payload['metro_boundary']['passed'] else 'FAIL'}",
        f"- 32×300 吞吐门: {'PASS' if throughput_pass else 'FAIL'}",
        "",
        "## 关键指标",
        f"- 块级总判: {'PASS' if decision['blocker_pass'] else 'FAIL'}",
        f"- 自动/黑箱 p50 最小比值: {metric['budget_ratio_min']:.3g}",
        f"- 达到最优比值预算: {metric['budget_budget_min']}",
        f"- 吞吐 32×300: {_fmt_metric(metric['throughput_current'])} (P0 baseline: {_fmt_metric(metric['throughput_baseline_32x300'])})",
        f"- 吞吐比: {_fmt_metric(metric['throughput_gate_ratio'])}",
        f"- 文献留出基线通过: {'PASS' if metric['p1_real_data_pass'] else 'FAIL' if metric['p1_real_data_pass'] is not None else 'N/A'}",
        "",
        "## 场景矩阵",
        "| 场景 | 结果 | 关键指标 |",
        "| --- | --- | --- |",
    ]
    for item in payload["scenarios"]:
        metrics = "; ".join(f"{name}={_fmt_metric(value)}" for name, value in item["metrics"].items())
        lines.append(f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | {metrics} |")

    lines.extend(
        [
            "",
            "## 合成4参数预算-误差（P1-03 / P1-04）",
            "| Budget | Autograd p50 | Black-box p50 | Autograd/Black-box |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for budget, auto_p50, black_p50, ratio in zip(
        curve["budgets"],
        curve["autograd_p50_error"],
        curve["black_box_p50_error"],
        curve["autograd_to_black_box_ratio"],
    ):
        lines.append(f"| {budget} | {_fmt_metric(auto_p50)} | {_fmt_metric(black_p50)} | {_fmt_metric(ratio)} |")

    lines.extend(
        [
            "",
            "## P1-05：JuPedSim 伪观测拟合",
            f"- Seed: {payload['jupedsim_pseudo_fit']['seed']}",
            f"- Budget: {payload['jupedsim_pseudo_fit']['budget_steps']}",
            f"- 基线损失: {payload['jupedsim_pseudo_fit']['baseline_loss']:.6g}",
            f"- 拟合后损失: {payload['jupedsim_pseudo_fit']['calibrated_loss']:.6g}",
            f"- 模型族差距: {payload['jupedsim_pseudo_fit']['model_gap']:.3g}",
            f"- 宏观差异: {payload['jupedsim_pseudo_fit']['macro_gap']:.3g}",
            "",
            "## P1-06：真实数据留出（Holdout）",
            "| Budget | 数据集 | 备注 | Train steps | Holdout steps | Train loss | Holdout loss | Holdout/Train | Relative error | Train macro | Holdout macro |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in real_data:
        lines.append(
            f"| {item['budget_steps']} | {item['dataset']} | {item['notes']} | {item['train_steps']} | "
            f"{item['holdout_steps']} | {item['train_loss']:.6g} | {item['holdout_loss']:.6g} | "
            f"{item['holdout_ratio_vs_train']:.3g} | {item['relative_parameter_error']:.3g} | "
            f"{item['train_macro_loss']:.6g} | {item['holdout_macro_loss']:.6g} |"
        )

    lines.extend(
        [
            "",
            "## 吞吐（P1-07）",
            "| Device | Batch | Slots | Agent-step/s | Peak MiB |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for benchmark in payload["benchmarks"]:
        peak = "—" if benchmark["peak_memory_mib"] is None else f"{benchmark['peak_memory_mib']:.1f}"
        lines.append(
            f"| {benchmark['device']} | {benchmark['batch_size']} | {benchmark['capacity']} | "
            f"{benchmark['agent_steps_per_second']:,.0f} | {peak} |"
        )

    lines.extend(
        [
            "",
            "## P1-08：论文骨架",
            f"- 研究主张：{payload['paper_outline']['central_claim']}",
            "- 图表（优先级）:",
        ]
    )
    for item in payload["paper_outline"]["figure_plan"]:
        lines.append(f"  - {item}")

    lines.extend(
        [
            "- 相关工作定位：",
            f"  - {payload['paper_outline']['related_work_positioning'][0]}",
            f"  - {payload['paper_outline']['related_work_positioning'][1]}",
            "",
            f"- 关联条件检查: {payload['paper_outline']['decision_branches'][-1]}",
        ]
    )
    return "\n".join(lines) + "\n"


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _fmt_metric(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and not math.isfinite(value):
        return "n/a"
    return str(value)
