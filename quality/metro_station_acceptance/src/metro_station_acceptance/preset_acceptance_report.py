"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from typing import Any


def render_preset_acceptance_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 自动布局预设端到端验收",
        "",
        f"总体结果：**{report['status']}**",
        "",
        f"负载：每类客流 {report['rate_per_hour']} 人/小时，注入 "
        f"{report['demand_minutes']} 分钟；seeds={report['seeds']}。",
        "",
        f"共 {report['totals']['runs']} 次运行、"
        f"{report['totals']['spawned_persons']} 名旅客、"
        f"{report['totals']['sampled_trajectories']} 条随机轨迹抽查。",
        "",
        "## 逐运行结果",
        "",
        "| 预设 | Seed | 生成/终态人数 | 清场时间(s) | JPS步数 | 抽查轨迹 | 结果 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for run in report["runs"]:
        samples = run.get("sampled_trajectories", [])
        sample_ok = sum(item.get("status") == "ok" for item in samples)
        lines.append(
            f"| {run['preset_id']} | {run['seed']} | "
            f"{run.get('spawned_persons', 0)}/{run.get('terminal_persons', 0)} | "
            f"{run.get('clearance_time_s')} | {run.get('jupedsim_steps', 0)} | "
            f"{sample_ok}/{len(samples)} | {run['status']} |"
        )

    lines.extend(
        [
            "",
            "## 随机旅客轨迹与拓扑抽查",
            "",
            "| 预设/Seed | 旅客 | 意图 | 距离(m) | 楼层序列 | 设施阶段 | 结果 |",
            "|---|---:|---|---:|---|---|---|",
        ]
    )
    for run in report["runs"]:
        for sample in run.get("sampled_trajectories", []):
            levels = " → ".join(sample.get("level_sequence", []))
            stages = " → ".join(sample.get("service_stage_sequence", []))
            lines.append(
                f"| {run['preset_id']}/{run['seed']} | {sample['passenger_id']} | "
                f"{sample.get('intent')} | {sample.get('distance_m')} | {levels} | "
                f"{stages} | {sample['status']} |"
            )

    failures = [
        (run, [name for name, value in run.get("checks", {}).items() if not value])
        for run in report["runs"]
        if run.get("status") != "ok"
    ]
    if failures:
        lines.extend(["", "## 待复核项", ""])
        for run, failed_checks in failures:
            lines.append(
                f"- `{run['preset_id']}` seed `{run['seed']}`："
                + ", ".join(failed_checks or [run.get("error", "unknown error")])
            )
    return "\n".join(lines) + "\n"
