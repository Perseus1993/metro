from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoalAuthorityViolation:
    path: str
    line: int
    rule: str
    detail: str


_GOAL_HANDLE_OWNERS = frozenset(
    {
        "runtime/passenger_goal_coordinator.py",
        "runtime/passenger_goal_runtime.py",
    }
)
_GOAL_COMMAND_EXECUTOR_OWNERS = frozenset(
    {
        "runtime/passenger_goal_command_executor.py",
        "testkit/goal_boarding_command_executor.py",
        "testkit/goal_gate_command_executor.py",
        "testkit/goal_journey_command_executor.py",
        "testkit/goal_stairs_command_executor.py",
    }
)
_REMOVED_LEGACY_FIELDS = frozenset(
    {
        "assigned_gate_id",
        "assigned_transport_id",
        "assigned_door_id",
        "legacy_index",
    }
)
_LEGACY_DECISION_CALLS = (
    "request_facility_choice",
    "preselect_facility_choice",
    "choose_platform",
    "plan.assign_facility",
)


def audit_goal_authority(package_root: Path) -> tuple[GoalAuthorityViolation, ...]:
    """Statically enforce ownership seams that runtime guards cannot express."""

    violations: list[GoalAuthorityViolation] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_audit_tree(tree, relative))
    return tuple(violations)


def _audit_tree(tree: ast.AST, relative: str) -> list[GoalAuthorityViolation]:
    violations: list[GoalAuthorityViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = _dotted_name(node)
            if _contains_removed_legacy_field(name):
                violations.append(
                    _violation(relative, node, "removed_legacy_field", name)
                )
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for target in _assignment_targets(node):
                name = _dotted_name(target)
                if name.endswith("goal_runtime.state"):
                    violations.append(
                        _violation(relative, node, "goal_state_owner", name)
                    )
        if not isinstance(node, ast.Call):
            continue
        call_name = _dotted_name(node.func)
        if call_name.endswith("goal_runtime.handle") and relative not in _GOAL_HANDLE_OWNERS:
            violations.append(_violation(relative, node, "goal_event_gateway", call_name))
        if _is_legacy_decision_call(call_name):
            violations.append(_violation(relative, node, "legacy_choice_boundary", call_name))
        if _uses_goal_queue_authority(node) and relative not in _GOAL_COMMAND_EXECUTOR_OWNERS:
            violations.append(_violation(relative, node, "queue_authority_owner", call_name))
        if _uses_goal_completion_authority(node) and relative not in _GOAL_COMMAND_EXECUTOR_OWNERS:
            violations.append(_violation(relative, node, "completion_authority_owner", call_name))
        if relative in _GOAL_COMMAND_EXECUTOR_OWNERS and _writes_legacy_plan(call_name):
            violations.append(_violation(relative, node, "executor_legacy_write", call_name))
    return violations


def _assignment_targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _uses_goal_queue_authority(node: ast.Call) -> bool:
    return any(
        keyword.arg == "authority"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == "goal_graph"
        for keyword in node.keywords
    )


def _uses_goal_completion_authority(node: ast.Call) -> bool:
    return any(
        keyword.arg == "goal_authorized"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )


def _writes_legacy_plan(call_name: str) -> bool:
    return call_name.endswith(("plan.assign_facility", "_assign_legacy_facility_index"))


def _is_legacy_decision_call(call_name: str) -> bool:
    return call_name.endswith(_LEGACY_DECISION_CALLS)


def _contains_removed_legacy_field(name: str) -> bool:
    return any(part in _REMOVED_LEGACY_FIELDS for part in name.split("."))


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _violation(
    path: str,
    node: ast.AST,
    rule: str,
    detail: str,
) -> GoalAuthorityViolation:
    return GoalAuthorityViolation(
        path=path,
        line=int(getattr(node, "lineno", 0)),
        rule=rule,
        detail=detail,
    )
