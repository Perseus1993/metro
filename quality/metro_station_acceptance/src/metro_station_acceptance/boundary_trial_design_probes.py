from __future__ import annotations

from .boundary_trial_constraint_probes import run_constraint_boundary_probe
from .boundary_trial_geometry_probes import run_geometry_boundary_probe
from .boundary_trial_queue_probes import run_queue_boundary_probe


def run_design_boundary_probe(group: str, variant: str) -> tuple[bool, tuple[str, ...]]:
    if group in {"A", "B"}:
        return run_geometry_boundary_probe(group, variant)
    if group == "D":
        return run_queue_boundary_probe(variant)
    if group == "E":
        return run_constraint_boundary_probe(variant)
    raise ValueError(f"unsupported design boundary group {group!r}")
