from __future__ import annotations

from math import isfinite
from typing import Any

from metro_station.adapters.simulation.design.schema import StationDesignDocument


FLOW_DEFINITIONS = {
    "enter_and_board": {
        "source_kind": "entrance",
        "operation_id": "entry_count_hour",
        "label": "Entry flow",
    },
    "exit_station": {
        "source_kind": "platform_edge",
        "operation_id": "exit_count_hour",
        "label": "Exit flow",
    },
    "transfer": {
        "source_kind": "platform_edge",
        "operation_id": "transfer_count_hour",
        "label": "Transfer flow",
    },
}
MAX_TOTAL_RATE_PER_HOUR = 120_000


def compile_demand_flows(
    nodes: list[dict[str, Any]],
    document: StationDesignDocument,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate editor flow bindings without leaking UI nodes into the station graph."""

    elements = document.element_by_id()
    flows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for index, node in enumerate(nodes):
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if not data.get("demand_flow"):
            continue
        path = f"demand_flows[{len(flows)}]"
        flow_id = str(data.get("flow_id") or node.get("id") or f"flow_{index}")
        intent = str(data.get("intent") or "")
        definition = FLOW_DEFINITIONS.get(intent)
        source_id = str(data.get("source_element_id") or "")
        target_id = str(data.get("target_element_id") or "") or None
        rate, rate_issue = _finite_rate(data.get("rate_per_hour"))
        flow = {
            "id": flow_id.removeprefix("flow:"),
            "intent": intent,
            "label": str(data.get("label") or (definition or {}).get("label") or intent),
            "source_element_id": source_id,
            "target_element_id": target_id,
            "rate_per_hour": rate,
            "operation_id": (definition or {}).get("operation_id"),
        }
        flows.append(flow)

        if flow["id"] in seen_ids:
            issues.append(_issue("demand.duplicate_id", path, f"Duplicate flow id {flow['id']!r}."))
        seen_ids.add(flow["id"])
        if definition is None:
            issues.append(_issue("demand.invalid_intent", f"{path}.intent", "Unknown flow intent."))
            continue
        if rate_issue:
            issues.append(_issue("demand.invalid_rate", f"{path}.rate_per_hour", rate_issue))

        source = elements.get(source_id)
        if source is None:
            issues.append(
                _issue(
                    "demand.source_missing",
                    f"{path}.source_element_id",
                    f"Flow source {source_id!r} does not exist.",
                )
            )
        elif source.kind != definition["source_kind"]:
            issues.append(
                _issue(
                    "demand.source_kind_invalid",
                    f"{path}.source_element_id",
                    f"{intent} must start at a {definition['source_kind']}.",
                )
            )

        if intent == "transfer":
            target = elements.get(target_id or "")
            if target is None:
                issues.append(
                    _issue(
                        "demand.transfer_target_missing",
                        f"{path}.target_element_id",
                        "Transfer flow needs a destination platform.",
                    )
                )
            elif target.kind != "platform_edge" or target.id == source_id:
                issues.append(
                    _issue(
                        "demand.transfer_target_invalid",
                        f"{path}.target_element_id",
                        "Transfer destination must be another platform edge.",
                    )
                )

    for intent, definition in FLOW_DEFINITIONS.items():
        total = sum(flow["rate_per_hour"] for flow in flows if flow["intent"] == intent)
        if total > MAX_TOTAL_RATE_PER_HOUR:
            issues.append(
                _issue(
                    "demand.total_rate_exceeded",
                    definition["operation_id"],
                    f"{definition['label']} total {total:g} p/h exceeds "
                    f"{MAX_TOTAL_RATE_PER_HOUR} p/h.",
                )
            )
    if (
        document.metadata.get("editor_scratch")
        and document.metadata.get("generation_state") == "generated"
        and not flows
    ):
        issues.append(
            _issue(
                "demand.required_for_scratch_station",
                "demand_flows",
                "A generated custom station needs at least one passenger flow.",
            )
        )
    return flows, issues


def operations_with_demand_flows(
    operations: dict[str, int | float],
    flows: list[dict[str, Any]],
    *,
    zero_unspecified: bool = False,
) -> dict[str, int | float]:
    result = dict(operations)
    if not flows:
        return result
    for intent, definition in FLOW_DEFINITIONS.items():
        matching = [flow for flow in flows if flow["intent"] == intent]
        if matching or zero_unspecified:
            result[definition["operation_id"]] = int(
                round(sum(flow["rate_per_hour"] for flow in matching))
            )
    return result


def _finite_rate(raw: Any) -> tuple[float, str | None]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0, "Flow rate must be a number."
    if not isfinite(value):
        return 0.0, "Flow rate must be finite."
    if value < 0:
        return 0.0, "Flow rate cannot be negative."
    if value > MAX_TOTAL_RATE_PER_HOUR:
        return value, f"Flow rate cannot exceed {MAX_TOTAL_RATE_PER_HOUR} p/h."
    return value, None


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"severity": "error", "code": code, "path": path, "message": message}
