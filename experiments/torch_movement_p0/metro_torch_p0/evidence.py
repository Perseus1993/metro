"""Create the P0 evidence bundle in the experiment directory only."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import torch

from .benchmark import run_benchmarks
from .calibration import run_calibration_evidence
from .integration import run_metro_boundary_smoke
from .scenarios import run_validation_scenarios


def generate_evidence(output_directory: Path) -> tuple[Path, Path, str]:
    """Run the complete P0 suite and save JSON plus a human-readable decision."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    scenarios = run_validation_scenarios(device)
    calibration = run_calibration_evidence(device)
    metro_boundary = run_metro_boundary_smoke(device)
    benchmarks = run_benchmarks()
    gpu_batch = next(
        (item for item in benchmarks if item.device == "cuda" and item.batch_size == 32 and item.capacity == 300),
        None,
    )
    all_scenarios_pass = all(item.passed for item in scenarios)
    throughput_pass = gpu_batch is not None and gpu_batch.agent_steps_per_second >= 500_000
    verdict = "GO: constrained P1 R&D"
    if not (all_scenarios_pass and calibration.passed and metro_boundary.passed and throughput_pass):
        verdict = "LIMITED-GO: resolve failed P0 gate before P1"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "scenarios": [asdict(item) for item in scenarios],
        "calibration": asdict(calibration),
        "metro_boundary": asdict(metro_boundary),
        "benchmarks": [asdict(item) for item in benchmarks],
        "decision": {
            "verdict": verdict,
            "scenario_gate": all_scenarios_pass,
            "calibration_gate": calibration.passed,
            "metro_boundary_gate": metro_boundary.passed,
            "gpu_throughput_gate": throughput_pass,
            "throughput_threshold_agent_steps_per_second": 500_000,
            "scope": "P1 R&D only; not a production backend switch or a JuPedSim replacement.",
        },
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "p0_evidence.json"
    markdown_path = output_directory / "P0_EVIDENCE.md"
    json_path.write_text(json.dumps(_json_safe(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return json_path, markdown_path, verdict


def _markdown(payload: dict) -> str:
    env = payload["environment"]
    decision = payload["decision"]
    lines = [
        "# Metro PyTorch Movement P0 — Evidence",
        "",
        f"- Generated (UTC): {payload['generated_at_utc']}",
        f"- Environment: Python {env['python']}; Torch {env['torch']}; CUDA {env['cuda_runtime']}; device {env['device']}",
        f"- Decision: **{decision['verdict']}**",
        "",
        "## Gate results",
        "",
        f"- M1–M7 movement scenarios: {'PASS' if decision['scenario_gate'] else 'FAIL'}",
        f"- Autograd + synthetic recovery: {'PASS' if decision['calibration_gate'] else 'FAIL'}",
        f"- Existing Metro `MovementBackend` injection smoke: {'PASS' if decision['metro_boundary_gate'] else 'FAIL'}",
        f"- GPU 32×300 throughput ≥ {decision['throughput_threshold_agent_steps_per_second']:,} agent-step/s: {'PASS' if decision['gpu_throughput_gate'] else 'FAIL'}",
        "",
        "## Movement scenarios",
        "",
        "| Scenario | Result | Key metrics |",
        "| --- | --- | --- |",
    ]
    for scenario in payload["scenarios"]:
        metrics = "; ".join(
            f"{key}={_format_metric(value)}" for key, value in scenario["metrics"].items()
        )
        lines.append(f"| {scenario['name']} | {'PASS' if scenario['passed'] else 'FAIL'} | {metrics} |")
    calibration = payload["calibration"]
    lines.extend(
        [
            "",
            "## Differentiable calibration",
            "",
            f"- Autograd / finite-difference gradient: {calibration['autograd_gradient']:.8f} / {calibration['finite_difference_gradient']:.8f}",
            f"- Relative gradient error: {calibration['relative_gradient_error']:.6%}",
            f"- Synthetic relaxation-time recovery: true {calibration['true_relaxation_time_s']:.3f}s → recovered {calibration['recovered_relaxation_time_s']:.3f}s",
            f"- Loss: {calibration['initial_loss']:.8g} → {calibration['final_loss']:.8g}",
            "",
            "## Throughput",
            "",
            "| Device | Batch | Slots | Agent-step/s | Peak MiB |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for benchmark in payload["benchmarks"]:
        peak = "—" if benchmark["peak_memory_mib"] is None else f"{benchmark['peak_memory_mib']:.1f}"
        lines.append(
            f"| {benchmark['device']} | {benchmark['batch_size']} | {benchmark['capacity']} | "
            f"{benchmark['agent_steps_per_second']:,.0f} | {peak} |"
        )
    metro = payload["metro_boundary"]
    lines.extend(
        [
            "",
            "## Metro boundary smoke",
            "",
            f"- Injected through existing constructor: {metro['injected']}",
            f"- Single passenger progressed: {metro['progressed_m']:.3f}m; retained tensor slots: {metro['active_slots']}",
            "",
            "## Scope and P1 blockers",
            "",
            "- The P0 adapter is in an experiment directory and handles only a rectangular envelope; it does not replace Metro's default JuPedSim backend.",
            "- M4 reached a worst numerical agent overlap of about 7.5 mm after sequential wall/agent projections. This is within the P0 1 cm tolerance but blocks production use until a joint contact solver is validated.",
            "- Polygonal walkable geometry, obstacles/stairs/escalators, queues/trains, formal JuPedSim parity, multi-seed statistics, and end-to-end operational acceptance remain P1/P2 work.",
        ]
    )
    return "\n".join(lines) + "\n"


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _format_metric(value) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        return "n/a"
    return str(value)
