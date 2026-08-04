"""HTML evidence sections specific to routing-algorithm experiments."""

from __future__ import annotations

from html import escape

from .comparison_report_tables import html_row, html_table


def algorithm_sections(report: dict) -> str:
    if not report.get("experiment_plan"):
        return ""
    execution = report.get("aggregate", {}).get("algorithm_execution", {})
    rows = []
    for role in ("baseline", "candidate"):
        item = execution.get(role, {})
        rows.append(
            html_row(
                role,
                item.get("algorithm_id"),
                item.get("algorithm_version"),
                item.get("parameters"),
                item.get("ok_runs"),
                item.get("failed_runs"),
                _percent(item.get("stability_rate")),
                _percent(item.get("failure_rate")),
                item.get("decision_log_count"),
            )
        )
    return (
        "<section><h2>算法版本、参数与稳定性</h2>"
        + html_table("角色,算法 ID,版本,参数,成功,失败,稳定率,失败率,决策日志", rows)
        + "<p>报告不根据单个种子自动生成算法优劣结论。</p></section>"
        + f"<section><h2>逐次路由决策日志</h2>{_decision_log_table(report)}</section>"
    )


def methodology_section(methodology: dict) -> str:
    if not methodology:
        return ""
    limitations = "".join(
        f"<li>{escape(str(item))}</li>" for item in methodology.get("limitations", [])
    )
    return (
        "<section><h2>方法与限制</h2>"
        f"<p>{escape(str(methodology.get('paired_inputs', '')))}</p>"
        f"<ul>{limitations}</ul></section>"
    )


def _decision_log_table(report: dict) -> str:
    rows = []
    for run in report.get("runs", []):
        for log in run.get("routing_decision_logs", []):
            rows.append(
                html_row(
                    run.get("role"),
                    run.get("seed"),
                    log.get("request_id"),
                    log.get("status"),
                    log.get("compute_duration_ms"),
                    log.get("topology_fingerprint"),
                    log.get("failure_code"),
                )
            )
    if not rows:
        return "<p>无路由决策日志；请检查实验是否包含疏散旅客。</p>"
    return html_table("角色,种子,请求 ID,状态,计算 ms,拓扑指纹,失败码", rows)


def _percent(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"
