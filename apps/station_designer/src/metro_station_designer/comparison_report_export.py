"""Self-contained decision report and evidence bundle export."""

from __future__ import annotations

import json
from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from metro_station.application.comparisons import ComparisonReport

from .algorithm_report_export import algorithm_sections, methodology_section
from .comparison_report_tables import (
    bottleneck_table as _bottleneck_table,
    control_event_table as _control_event_table,
    html_row as _row,
    html_table as _table,
)


def comparison_report_bundle(report: ComparisonReport) -> bytes:
    payload = report.as_dict()
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("baseline.analysis-case.json", _json(payload["spec"]["baseline"]))
        archive.writestr("candidate.analysis-case.json", _json(payload["spec"]["candidate"]))
        archive.writestr("comparison-report.json", _json(payload))
        if payload.get("experiment_plan"):
            archive.writestr("experiment-plan.json", _json(payload["experiment_plan"]))
            archive.writestr(
                "analysis-case.json",
                _json(payload["experiment_plan"]["analysis_case"]),
            )
        archive.writestr("decision-report.html", _report_html(payload))
    return output.getvalue()


def _report_html(report: dict) -> str:
    aggregate = report.get("aggregate", {})
    baseline = aggregate.get("baseline", {})
    candidate = aggregate.get("candidate", {})
    deltas = aggregate.get("candidate_minus_baseline", {})
    decision = report.get("decision", {})
    evidence = report.get("evidence", {})
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>方案对比决策报告</title>
<style>{_STYLE}</style></head><body><main>
<h1>方案对比决策报告</h1>
<p class="meta">实验 {escape(str(report.get("spec", {}).get("experiment_id", "")))} · 状态 {escape(str(report.get("status", "")))}</p>
<section><h2>复跑信息</h2>{_provenance_table(report.get("spec", {}))}</section>
<section><h2>分析结论</h2>
<p><strong>{escape(str(decision.get("recommendation", "more_evidence")))}</strong></p>
<p>{escape(str(decision.get("rationale", "")))}</p>
<p>分析人：{escape(str(decision.get("analyst", "未记录")))}</p></section>
<section><h2>汇总指标</h2>{_metric_table(baseline, candidate, deltas)}</section>
{algorithm_sections(report)}
<section><h2>逐种子配对</h2>{_paired_table(report.get("paired_results", []))}</section>
<section><h2>管控事件</h2>{_control_event_table(report.get("runs", []))}</section>
<section><h2>峰值与主要瓶颈</h2>{_bottleneck_table(report.get("runs", []))}</section>
<section><h2>输入差异</h2>{_difference_table(report.get("input_differences", []))}</section>
<section><h2>证据状态与使用边界</h2>{_evidence_block(evidence)}</section>
{methodology_section(report.get("methodology", {}))}
</main></body></html>"""


def _metric_table(baseline: dict, candidate: dict, deltas: dict) -> str:
    rows = []
    for metric, delta in deltas.items():
        baseline_value = baseline.get("metrics", {}).get(metric, {}).get("mean")
        candidate_value = candidate.get("metrics", {}).get(metric, {}).get("mean")
        rows.append(
            _row(
                metric,
                baseline_value,
                candidate_value,
                delta.get("mean_delta"),
                _percent(delta.get("mean_relative_change")),
                delta.get("sample_count"),
            )
        )
    return _table("指标,基准均值,候选均值,候选−基准,相对变化,n", rows)


def _paired_table(pairs: list[dict]) -> str:
    rows = []
    for pair in pairs:
        metrics = pair.get("metrics", {})
        rows.append(
            _row(
                pair.get("seed"),
                pair.get("status"),
                _delta(metrics, "clearance_time_s"),
                _delta(metrics, "peak_density_persons_m2"),
                _delta(metrics, "stuck_agents"),
            )
        )
    return _table("种子,状态,清场 Δs,峰值密度 Δ,滞留 Δ", rows)


def _difference_table(differences: list[dict]) -> str:
    rows = [
        _row(item.get("kind"), item.get("path"), item.get("before"), item.get("after"))
        for item in differences
    ]
    return _table("类型,路径,变更前,变更后", rows) if rows else "<p>无决策相关输入差异。</p>"


def _provenance_table(spec: dict) -> str:
    baseline = spec.get("baseline", {})
    candidate = spec.get("candidate", {})
    simulation = baseline.get("simulation", {})
    return _table(
        "基准指纹,候选指纹,种子,需求窗口 min,清场窗口 min,步长 s",
        [
            _row(
                baseline.get("semantic_fingerprint"),
                candidate.get("semantic_fingerprint"),
                spec.get("seeds"),
                simulation.get("demand_minutes"),
                simulation.get("horizon_minutes"),
                simulation.get("tick_seconds"),
            )
        ],
    )


def _evidence_block(evidence: dict) -> str:
    rows = []
    for role in ("baseline", "candidate"):
        item = evidence.get(role, {})
        rows.append(
            _row(
                role,
                item.get("calibration_status"),
                item.get("model_version"),
                item.get("safe_use_boundary"),
            )
        )
    return _table("方案,校准状态,模型版本,安全使用边界", rows)


def _delta(metrics: dict, metric: str):
    return metrics.get(metric, {}).get("delta")


def _percent(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


_STYLE = """
body{margin:0;background:#f4f7f8;color:#172026;font:15px/1.55 system-ui,sans-serif}
main{max-width:1120px;margin:32px auto;padding:32px;background:white;border-radius:12px}
h1,h2{color:#103a45}h2{margin-top:28px}.meta{color:#5d7077}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px;border:1px solid #d8e0e3;text-align:left;vertical-align:top}
th{background:#eaf1f3}td{max-width:360px;overflow-wrap:anywhere}section{break-inside:avoid}
"""
