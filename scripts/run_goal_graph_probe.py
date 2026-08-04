from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_testkit.goal_probe_scenarios import (  # noqa: E402
    run_goal_probe_scenarios,
)


DEFAULT_OUTPUT_DIR = ROOT / "output" / "goal_graph_probe"
DEFAULT_JSON_OUT = DEFAULT_OUTPUT_DIR / "goal_graph_probe.json"
DEFAULT_MARKDOWN_OUT = DEFAULT_OUTPUT_DIR / "goal_graph_probe.md"


def build_report() -> dict[str, Any]:
    scenarios = run_goal_probe_scenarios()
    return {
        "generated_by": "pure GoalStateMachine single-passenger probe",
        "scope": "station entrance -> entry gate -> paid hall",
        "summary": {
            "status": "ok" if all(item.status == "ok" for item in scenarios) else "review",
            "scenario_count": len(scenarios),
            "passed_scenarios": sum(item.status == "ok" for item in scenarios),
            "total_steps": sum(len(item.steps) for item in scenarios),
            "uses_mesa": False,
            "uses_jupedsim": False,
        },
        "scenarios": [item.as_dict() for item in scenarios],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 单旅客进站闸机 Goal Graph 探针",
        "",
        f"- 总体状态：`{summary['status']}`",
        f"- 场景：{summary['passed_scenarios']} / {summary['scenario_count']} 通过",
        f"- 状态步骤：{summary['total_steps']}",
        "- 执行环境：纯领域状态机，不使用 Mesa/JuPedSim",
        "",
    ]
    for scenario in report["scenarios"]:
        lines.extend(_scenario_markdown(scenario))
    return "\n".join(lines).rstrip() + "\n"


def _scenario_markdown(scenario: dict[str, Any]) -> list[str]:
    lines = [
        f"## {scenario['label']}",
        "",
        f"预期：{scenario['expected_outcome']}",
        "",
        f"结果：`{scenario['status']}`",
        "",
        "| 步骤 | 时间 | 输入事件 | 之前 | 之后 | 承诺设施 | handled | 输出命令 | 说明 |",
        "|---:|---:|---|---|---|---|---|---|---|",
    ]
    for step in scenario["steps"]:
        before = _state_label(step["before_node"], step["before_interaction"])
        after = _state_label(step["after_node"], step["after_interaction"])
        commands = ", ".join(command["kind"] for command in step["commands"]) or "—"
        lines.append(
            "| {index} | {time:g} | `{event}` | `{before}` | `{after}` | `{facility}` | "
            "{handled} | `{commands}` | {note} |".format(
                index=step["index"],
                time=step["time_seconds"],
                event=step["event_kind"],
                before=before,
                after=after,
                facility=step["after_facility"] or "—",
                handled="是" if step["handled"] else "否",
                commands=commands,
                note=step["note"],
            )
        )
    lines.extend(
        [
            "",
            "检查："
            + "；".join(
                f"{name}={'通过' if passed else '失败'}"
                for name, passed in scenario["checks"].items()
            ),
            "",
        ]
    )
    return lines


def _state_label(node: str | None, interaction: str | None) -> str:
    if node is None:
        return "—"
    return node if interaction is None else f"{node}/{interaction}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pure single-passenger Goal Graph probes")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MARKDOWN_OUT)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_out.write_text(render_markdown(report), encoding="utf-8")
    if not args.quiet:
        print(
            f"[GOAL-GRAPH] status={report['summary']['status']} "
            f"scenarios={report['summary']['passed_scenarios']}/"
            f"{report['summary']['scenario_count']}"
        )
        print(f"[GOAL-GRAPH] json={args.json_out.resolve()}")
        print(f"[GOAL-GRAPH] markdown={args.markdown_out.resolve()}")
    return 0 if report["summary"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
