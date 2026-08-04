# Metro Torch Movement P0

This folder is a self-contained Phase 0 experiment. It does not modify the
official `metro_station` runtime, its dependency lock, or existing experiments.

The experiment implements a fixed-slot, mask-based PyTorch pedestrian kernel,
seven deterministic micro-scenarios, CPU/CUDA measurements, and a synthetic
gradient-calibration check. It is a feasibility artefact, not a validated
pedestrian model or a JuPedSim replacement.

## Local environment

```powershell
cd D:\metro\experiments\torch_movement_p0
uv sync --extra metro --group dev
uv run metro-torch-p0 --out evidence
uv run pytest -q
```

The environment is intentionally local to this directory. Do not set
`KMP_DUPLICATE_LIB_OK`; a duplicate OpenMP runtime is a failed environment
precondition rather than an acceptable workaround.

## Output

The command writes an independently inspectable evidence bundle under `evidence/`:

- `p0_evidence.json` — machine-readable environment, scenario, benchmark, calibration, and gate data.
- `P0_EVIDENCE.md` — a concise decision report with scope limitations.

The decision is a research investment decision, not a product release decision.

## What the P0 proves

- M1–M7 deterministic checks cover free walking, head-on interaction,
  bidirectional flow, bottleneck flow, slot reuse, level isolation, and a
  dynamic obstacle.
- The movement boundary can accept the experimental backend through Metro's
  existing `MovementBackend` constructor injection without source changes.
- A relaxation-time parameter receives an autograd gradient, agrees with a
  central finite difference, and is recoverable from synthetic trajectories.
- CUDA performance is measured with fixed slots at 300/1,024-agent workload
  points.

The kernel is clean-room P0 code. It intentionally has no polygonal walkable
geometry, JuPedSim parity, facility/train integration, or claim of calibrated
pedestrian validity. The bottleneck check allows at most 1 cm numerical overlap
while sequential wall/agent projections are being hardened; that is a P1
blocker, not an operational safety guarantee.
