from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil
from .artifact_contract import validate_runner_artifacts


def run_case(target_agents: int, *, timeout_seconds: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"metro-spike-{target_agents}-") as folder:
        root = Path(folder)
        output = root / "output"
        output.mkdir()
        spec = _spec(target_agents)
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        log_path = root / "child.log"
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "metro_cloud_api.child", "real",
                 str(spec_path), str(output)],
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            peak_rss, timed_out = _monitor(process, started, timeout_seconds)
        stdout = log_path.read_text(encoding="utf-8", errors="replace")
        result_path = output / "_result.json"
        result = json.loads(result_path.read_text("utf-8")) if result_path.exists() else None
        contract = validate_runner_artifacts(output)
        return {
            "target_agents": target_agents,
            "return_code": process.returncode,
            "timed_out": timed_out,
            "wall_seconds": round(time.monotonic() - started, 3),
            "peak_rss_bytes": peak_rss,
            "result": result,
            "contract": contract,
            "stdout_tail": stdout.splitlines()[-20:],
        }


def _monitor(
    process: subprocess.Popen[str], started: float, timeout_seconds: float
) -> tuple[int, bool]:
    peak_rss = 0
    while process.poll() is None:
        peak_rss = max(peak_rss, _rss(process.pid))
        if time.monotonic() - started > timeout_seconds:
            _terminate_tree(process.pid)
            process.wait(timeout=10)
            return peak_rss, True
        time.sleep(0.1)
    return peak_rss, False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run each capacity case in a fresh process")
    parser.add_argument("--agents", nargs="+", type=int, default=[25, 50, 100, 200])
    parser.add_argument("--timeout-seconds", type=float, default=14_400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    for value in args.agents:
        result = run_case(value, timeout_seconds=args.timeout_seconds)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.output is not None:
            args.output.write_text(
                json.dumps({"runner": "real", "cases": results}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
    payload = {"runner": "real", "cases": results}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if any(
        case["return_code"] != 0 or case["timed_out"] or not case["contract"]["valid"]
        for case in results
    ):
        raise SystemExit(1)


def _spec(target_agents: int) -> dict[str, Any]:
    if target_agents < 1 or target_agents > 1000:
        raise ValueError("target_agents must be between 1 and 1000")
    return {
        "station": "小寨", "hour": 18, "design_template": "visual_demo_station",
        "scenario_mode": "operations", "horizon_minutes": 15, "demand_minutes": 10,
        "tick_seconds": 1, "entry_count_hour": target_agents * 6,
        "exit_count_hour": 0, "transfer_count_hour": 0, "group_size": 1, "admins": 0,
        "initial_platform_persons": 0, "alarm_delay_seconds": 0.0,
        "movement_backend": "jupedsim", "jupedsim_model": "collision_free_speed",
        "clock_mode": "physical", "routing_algorithm": "builtin_shortest_path", "seed": 42,
        "trajectory_sample_seconds": 10, "_estimated_passenger_agents": target_agents,
    }


def _rss(pid: int) -> int:
    try:
        root = psutil.Process(pid)
        return sum(
            process.memory_info().rss
            for process in [root, *root.children(recursive=True)]
            if process.is_running()
        )
    except psutil.Error:
        return 0


def _terminate_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        processes = [*root.children(recursive=True), root]
        for process in processes:
            process.kill()
        psutil.wait_procs(processes, timeout=5)
    except psutil.Error:
        return


if __name__ == "__main__":
    main()
