"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .layout_acceptance_contract import LAYOUT_IDS
from .operational_acceptance_scenarios import OPERATIONAL_SCENARIOS


def merge_layout_acceptance_payloads(
    payloads: Sequence[Mapping[str, Any]],
    *,
    required_layout_ids: tuple[str, ...] = LAYOUT_IDS,
) -> dict[str, Any]:
    if not payloads:
        raise ValueError("at least one layout acceptance report is required")
    tiers = {str(payload.get("tier")) for payload in payloads}
    seeds = {tuple(payload.get("seeds", ())) for payload in payloads}
    if len(tiers) != 1 or len(seeds) != 1:
        raise ValueError("layout acceptance reports must use the same tier and seeds")
    layouts = [
        dict(layout)
        for payload in payloads
        for layout in payload.get("layouts", ())
        if isinstance(layout, Mapping)
    ]
    layout_ids = tuple(str(layout.get("layout_id")) for layout in layouts)
    if len(set(layout_ids)) != len(layout_ids):
        raise ValueError("layout acceptance reports contain duplicate layouts")
    ordered = tuple(
        next(layout for layout in layouts if layout["layout_id"] == layout_id)
        for layout_id in required_layout_ids
        if any(layout["layout_id"] == layout_id for layout in layouts)
    )
    selected_seeds = next(iter(seeds))
    check_shapes = {
        tuple(layout.get("checks", {})) for layout in ordered
    }
    checks = {
        "all_requested_layouts_reported": tuple(
            layout["layout_id"] for layout in ordered
        )
        == required_layout_ids,
        "all_layouts_mature": bool(ordered)
        and all(layout.get("status") == "ok" for layout in ordered),
        "same_maturity_contract": len(check_shapes) == 1,
        "journey_matrix_complete": all(
            len(layout["journeys"]["normal"]) == len(selected_seeds)
            and len(layout["journeys"]["evacuation"]) == len(selected_seeds)
            for layout in ordered
        ),
        "operational_matrix_complete": all(
            len(layout["operations"]["reports"])
            == len(selected_seeds) * len(OPERATIONAL_SCENARIOS)
            for layout in ordered
        ),
    }
    return {
        "schema_version": "layout_acceptance.v1",
        "status": "ok" if checks and all(checks.values()) else "review",
        "tier": next(iter(tiers)),
        "layout_ids": required_layout_ids,
        "seeds": selected_seeds,
        "layouts": ordered,
        "checks": checks,
    }


def render_merged_layout_acceptance_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Cross-layout maturity acceptance",
        "",
        f"- Tier: `{payload['tier']}`",
        f"- Seeds: `{', '.join(str(seed) for seed in payload['seeds'])}`",
        f"- Status: **{str(payload['status']).upper()}**",
        "",
        "| Layout | Contract | Journeys | Operations | Clearance | Determinism | Status |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for layout in payload["layouts"]:
        checks = layout["checks"]
        lines.append(
            "| {layout_id} | {contract} | {journeys} | {operations} | {clearance} | {determinism} | {status} |".format(
                layout_id=layout["layout_id"],
                contract=layout["contract"]["status"],
                journeys=layout["journeys"]["status"],
                operations=layout["operations"]["status"],
                clearance=_pass_fail(checks["strict_clearance_all_runs"]),
                determinism=_pass_fail(checks["deterministic_replay"]),
                status=layout["status"],
            )
        )
    lines.extend(["", "## Blocking checks", ""])
    failures = [name for name, passed in payload["checks"].items() if not passed]
    for layout in payload["layouts"]:
        failures.extend(
            f"{layout['layout_id']}.{name}"
            for name, passed in layout["checks"].items()
            if not passed
        )
    lines.extend(f"- `{failure}`" for failure in failures)
    if not failures:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _pass_fail(value: bool) -> str:
    return "pass" if value else "fail"
