"""HTML tables for run-level comparison and control-event evidence."""

from __future__ import annotations

import json
from html import escape
from typing import Any


def control_event_table(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        for event in run.get("control_events", []):
            scheduled = _number(event.get("scheduled_seconds"))
            applied = _number(event.get("applied_seconds"))
            rows.append(
                html_row(
                    run.get("role"),
                    run.get("seed"),
                    event.get("measure_id"),
                    event.get("measure_kind"),
                    event.get("action"),
                    scheduled,
                    applied,
                    None if scheduled is None or applied is None else applied - scheduled,
                    event.get("status"),
                    event.get("level_id"),
                    event.get("target_id"),
                    event.get("details", {}).get("reason"),
                )
            )
    if not rows:
        return "<p>无管控事件。</p>"
    return html_table(
        "方案,种子,措施 ID,类型,动作,计划时刻 s,应用时刻 s,偏差 s,状态,楼层,目标,原因",
        rows,
    )


def bottleneck_table(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        bottleneck = run.get("top_bottleneck") or {}
        density = run.get("peak_density_location") or {}
        rows.append(
            html_row(
                run.get("role"),
                run.get("seed"),
                run.get("status"),
                run.get("right_censored"),
                bottleneck.get("label") or bottleneck.get("facility_id"),
                bottleneck.get("time_seconds"),
                bottleneck.get("pressure"),
                density.get("level_id"),
                density.get("time_seconds"),
                run.get("density_duration_above_threshold_s"),
                run.get("error"),
            )
        )
    return html_table(
        "方案,种子,状态,右删失,主要瓶颈,瓶颈时刻 s,压力,密度楼层,峰值时刻 s,超阈持续 s,错误",
        rows,
    )


def html_table(headers: str, rows: list[str]) -> str:
    cells = "".join(f"<th>{escape(value)}</th>" for value in headers.split(","))
    return f"<table><thead><tr>{cells}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def html_row(*values: Any) -> str:
    return "<tr>" + "".join(f"<td>{escape(_display(value))}</td>" for value in values) + "</tr>"


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
