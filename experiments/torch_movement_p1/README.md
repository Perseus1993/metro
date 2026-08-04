# Metro Torch Movement P1 (PM-033)

This directory is a self-contained PM-033 workspace. It does not modify
`metro_station` defaults, dependency locks, or existing experiments.

## 目标与隔离边界

- 自成实验包：所有实现和产物都在 `experiments/torch_movement_p1/` 下。
- 不改动 `packages/metro_station` 或现有运行配置；
- 任何对上层后端的改动仅通过 `ExperimentalTorchMovementBackend` 作为可注入可选入口。

## Scope

- P1-01: Joint agent/wall contact solving (replacing sequential projection)
- P1-02: Polygonal walkable-domain tensorization (concavity, holes, obstacles, geometry refresh)
- P1-03/04: Calibration framework with 4-parameter synthetic recovery
- P1-05: JuPedSim pseudo-observation fitting
- P1-06: Real-data-like holdout protocol
- P1-07: Throughput maintenance harness and regression gate
- P1-08: Evidence + decision + paper-outline generation

The P1-01 blocker includes `P1-01_joint_contact_300`: a 300-slot dense
rollout checks minimum agent/wall clearance and a non-zero progress threshold.

The adapter remains optional and is used only to validate constructor-injection
boundary behavior in Metro. JuPedSim remains the production default backend.

## 当前执行状态（按你给的PM-033）

- W1~W2 blocker: PASS（`metro-torch-p1 blocker --device cpu`）
- W3~W4 synthetic: 能产生预算-误差曲线（见下文 `evidence_fast`）
- W5~W6 pseudo-fit/throughput：可产出，`throughput` 已通过可复跑
- W7~W8 evidence/decision：`evidence_p1_juelich_final` 已产出；当前四选一为 `limited-go`（blocker、梯度、边界 smoke、吞吐均通过，合成预算优势未达 paper-go 阈值）

当前示例证据文件:
- `evidence_fast/P1_EVIDENCE.md`
- `evidence_fast/p1_evidence.json`
- `evidence_p1_final_v2/P1_EVIDENCE.md`
- `evidence_p1_final_v2/p1_evidence.json`
- `evidence_p1_juelich_final/P1_EVIDENCE.md`
- `evidence_p1_juelich_final/p1_evidence.json`

## Local environment

```powershell
cd D:\metro\experiments\torch_movement_p1
uv sync --extra metro --group dev
```

Run plans:

```powershell
uv run metro-torch-p1 blocker --device cpu
uv run metro-torch-p1 evidence --out evidence_fast --device cpu --synthetic-budgets 2 4 --synthetic-seeds 7 11 --synthetic-steps 16 --real-budgets 20 40 --real-steps 32
uv run metro-torch-p1 calibration --device cpu --budget 80
uv run metro-torch-p1 synthetic --device cuda --budgets 20 40 80 160
uv run metro-torch-p1 pseudo-fit --device cuda --seed 17 --budget 120
uv run metro-torch-p1 real-data --device cuda --steps 120
uv run metro-torch-p1 throughput
  uv run metro-torch-p1 evidence --out evidence_fast --device cpu
```

## Outputs

- `evidence/P1_EVIDENCE.md`: decision-readable report
- `evidence/p1_evidence.json`: machine-readable payload for archives
- `evidence_fast/*`: 同步命名的快速版（建议用于日常迭代，预算较小、可控）

Do not change Metro runtime behavior when consuming these outputs.

Suggested PM-033 milestone execution:

- W1~W2: `metro-torch-p1 blocker`
- W3~W4: `metro-torch-p1 synthetic`（或 `calibration`）
- W5~W6: `metro-torch-p1 pseudo-fit` + `throughput`
- W7~W8: `metro-torch-p1 evidence --real-dataset <Jülich dataset path>`

## Current blockers reflected in code

- M4 overlap tolerance for P1-01 is tightened to `-1mm` in acceptance criteria.
- P1-02 has dedicated scenarios (`P1-02_polygon_walkable_50`,
  `P1-02_geometry_refresh_tick`) that are part of the blocker gate.
