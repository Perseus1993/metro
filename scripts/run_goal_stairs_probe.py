from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_testkit.goal_stairs_probe import (  # noqa: E402
    GOAL_STAIRS_COMPONENT_PROBE,
)


DEFAULT_OUTPUT_DIR = ROOT / "output" / "goal_stairs_probe"
DEFAULT_JSON_OUT = DEFAULT_OUTPUT_DIR / "goal_stairs_probe.json"
DEFAULT_MARKDOWN_OUT = DEFAULT_OUTPUT_DIR / "goal_stairs_probe.md"


def build_report(*, seed: int = 42, max_seconds: float = 60.0) -> dict[str, Any]:
    return GOAL_STAIRS_COMPONENT_PROBE.run(seed=seed, max_seconds=max_seconds)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 单旅客楼梯 Graph × JuPedSim 物理探针",
        "",
        f"- 状态：`{summary['status']}`",
        f"- 场景：{summary['passed_scenarios']} / {summary['scenario_count']} 通过",
        f"- Graph事件步骤：{summary['trace_steps']}",
        f"- JuPedSim乘客步：{summary['jupedsim_steps']}",
        f"- 垂直服务事件：{summary['vertical_service_events']}",
        f"- 联合组件：{', '.join(report['component_ids'])}",
        f"- 随机种子：{report['seed']}",
        "",
    ]
    for scenario in report["scenarios"]:
        lines.extend(_scenario_markdown(scenario))
    return "\n".join(lines).rstrip() + "\n"


def _scenario_markdown(scenario: dict[str, Any]) -> list[str]:
    lines = [
        f"## {scenario['scenario_id']}",
        "",
        f"- 结果：`{scenario['status']}`",
        f"- 物理耗时：{scenario['elapsed_seconds']} 秒",
        f"- 最终Graph节点：`{scenario['final_state']['current_node_id']}`",
        f"- 最终楼层：`{scenario['final_level_id']}`",
        "- 检查："
        + "；".join(
            f"{name}={'通过' if passed else '失败'}"
            for name, passed in scenario["checks"].items()
        ),
        "",
        "| # | t | 事件 | 物理位置 | 楼层 | Graph之前 | Graph之后 | 楼梯 | 阻挡 | 命令 |",
        "|---:|---:|---|---|---|---|---|---|---:|---|",
    ]
    for trace in scenario["traces"]:
        commands = ", ".join(trace["commands"]) or "—"
        position = f"({trace['position'][0]:.2f}, {trace['position'][1]:.2f})"
        lines.append(
            "| {index} | {time:g} | `{event}` | `{position}` | `{level}` | `{before}` | "
            "`{after}` | `{facility}` | {blockers} | `{commands}` |".format(
                index=trace["index"],
                time=trace["time_seconds"],
                event=trace["event_kind"],
                position=position,
                level=trace["current_level_id"],
                before=trace["before_graph_state"],
                after=trace["after_graph_state"],
                facility=trace["committed_facility_id"] or "—",
                blockers=trace["blocker_count"],
                commands=commands,
            )
        )
    lines.append("")
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Goal Graph with a JuPedSim stairs micro scene"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-seconds", type=float, default=60.0)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MARKDOWN_OUT)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(seed=args.seed, max_seconds=args.max_seconds)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_out.write_text(render_markdown(report), encoding="utf-8")
    if not args.quiet:
        print(
            f"[GOAL-STAIRS] status={report['summary']['status']} "
            f"scenarios={report['summary']['passed_scenarios']}/"
            f"{report['summary']['scenario_count']}"
        )
        print(f"[GOAL-STAIRS] json={args.json_out.resolve()}")
        print(f"[GOAL-STAIRS] markdown={args.markdown_out.resolve()}")
    return 0 if report["summary"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
