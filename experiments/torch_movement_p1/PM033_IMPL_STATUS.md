# PM-033 P1 实施对照（当前可交付状态）

目标：在不改 `metro_station` 默认后端、不打断师兄分支的前提下，完成
PM-033 的 P1 证据闭环。

## 已完成项

| 工单 | 目标 | 结果 |
|---|---|---|
| P1-01 | 联合接触求解 | 已用 `contact.py` 的 `solve_joint_contacts` 替代顺序投影；新增 `P1-01_joint_contact_300`，300 槽位穿透与锁死门通过。 |
| P1-02 | 多边形几何张量化 | 已支持外轮廓+孔洞+障碍转线段、点-in-polygon 过滤、几何刷新。 |
| P1-03 | 标定框架 | 支持 `autograd` / `black-box` / `l-bfgs` / `cma-es` / `bayes`，统一预算单位=步数。 |
| P1-04 | 合成4参数恢复 | 已生成预算-误差曲线（默认 `budgets=[20,40,80,160]`，`seeds>=10`）。 |
| P1-05 | JuPedSim 伪观测拟合 | 已有 `pseudo-fit`，并在报告里区分模型族差距与真实拟合结论。 |
| P1-06 | 真实数据留出 | 已接入 Jülich `fd1_n14.txt`（TXT Person/Frame/X/Y），训练/留出 84/36 步可复跑；仍不把回退数据当真实证据。 |
| P1-07 | 吞吐维持 | `throughput` 命令已包含 `32×300` 与 CPU/CUDA 回归点。 |
| P1-08/09 | 证据+决策+评审 | 已有 `evidence` 命令产出 JSON/MD，带四选一决策输出。 |

## 当前验证（你当前环境）

- Blocker：`PASS`（10 项场景）
- P1-01 dense contact：`PASS`（300 agents；min gap/wall clearance ≥ -1mm，progress > 0.05m）
- 合成预算-误差：可复现，可输出 `p50/p95`
- 伪观测/真实链路：可跑通；`evidence_p1_juelich_final` 使用真实 Jülich TXT 轨迹
- 吞吐：`PASS`；最终证据包中的 32×300 为约 `1.34e6 agent-step/s`（P0 基线约 `9.98e5`）
- 四选一：`limited-go`（吞吐能力保留；合成梯度优势当前未达到 ≤50% 预算判据）

## 当前 limited-go 的真实原因

1. `run_validation_scenarios`、梯度门、Metro boundary smoke、吞吐门全部通过；
2. 合成预算曲线的最佳 autograd/black-box p50 比值约 `0.825`，未达到 paper-go 的 `≤0.50`；
3. Jülich 留出结果已产出，但当前没有预先登记的文献误差阈值，因此文献基线判定保持 N/A。

## 与师兄主线隔离说明

- 所有代码在 `experiments/torch_movement_p1/` 下；
- 未修改 `packages/metro_station` 或现有默认后端路径；
- 默认运行 `metro-torch-p1` 命令不替换生产依赖链。  

## 下步建议

1. 由评审决定是否按 `limited-go` 冻结标定线并转入批量敏感性实验；
2. 若要 `paper-go`，先登记可核验的文献 holdout 阈值并扩展多场景/多种子曲线；
3. 按 `docs/product/PM-033_TORCH_CALIBRATION_P1.md` 产出正式评审纪要。  
