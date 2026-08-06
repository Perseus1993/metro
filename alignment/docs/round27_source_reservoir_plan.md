# Round 27 工作单：Source Reservoir 与物理背压

交接自 Round 26（code freeze `01f64607`，review parent `27e57b4c`）。

---

## 0. 一句话定位

**Round 26 修复了站内下游服务链；Round 27 要把站外需求、车内下车清单和站内物理占用分开。**

本轮不是继续给 admission 主路径打补丁。核心对象只有两个：无限逻辑 entry source，
以及有限、绑定列车且受发车截止约束的 alighting manifest。二者通过同一套 transactional
publication 状态机进入站内，但不能合并等待语义或指标。

## 1. 已冻结的决策

1. Entry 可在未建模站外空间无限逻辑排队；pending 不占站内容量。
2. Alighting 是有限列车清单，绑定 `(platform_id, arrival_sequence)`。
3. 默认发车策略为 `FAIL_CAPACITY`：截止时仍有未下车者，结果为
   `train_alighting_capacity_insufficient`，无成功发车，不转后车，不隐式延长停站。
4. 临时容量不足返回 typed wait；无效拓扑、零认证容量、永远不可能的 group size fail-fast。
5. Passenger 只在 admission credit、具体 body-clear owner 和 placement 全部成功后发布；
   发布失败必须补偿，不允许半成品 agent 或 token bypass。
6. `source_wait` 只按 entry boundary 或 train run 输出，禁止池化 headline duration。
7. Dynamic、clearance、stress 是三套门，不再用固定 horizon 的 `spawned==scheduled` 覆盖全部。
8. Round 26 的 replan 与 placement retry `<=1%` 继续作为不可放宽的回归门。

详见 `docs/architecture/ADR-010-external-source-reservoir-and-backpressure.md`。

## 2. 合并前阻塞项

### B0 — 基线与 same-tick 归属

- 当前分支必须包含 `01f64607`。
- same-tick 在 `55543e2b` 与 `27e57b4c` 均为 `expected 4 / actual 1`，归为既有失败。
- 禁止用增大 reservoir/token 容量掩盖。
- 证据：`alignment/output/round27/B0_baseline_and_same_tick_provenance.json`。

### B1 — 清空预测当前不可用

正式 10 分钟排程的最后 exit release 是 step 614，所以预测截点是 615，不是 600。
当前没有正的无条件 `mu_min` 或有限 downstream tail；因此预注册状态必须是
`prediction_unavailable`，不得先跑出清空时间再反写预测。

- 证据：`alignment/output/round27/T0_preregistered_prediction_contract.json`。
- 先修 backpressure，再用固定 240-step 周期和 seeds 41–45 资格化；46–50 held-out。

## 3. Phase 1 — 领域内核

### T1 — ExternalDemandReservoir

- 稳定 ticket id、scheduled step、intent、group size、source kind/ref。
- FIFO `enqueue -> claim -> defer|commit`，禁止 double claim/double publish。
- Entry ticket 可持续等待；train ticket 必须有 run id 与 deadline。
- close 输出 right-censored residence；per-boundary wait 不池化。
- 纯单测覆盖顺序、守恒、补偿和 invalid transition。

### T2 — TrainExchangeManifest

必须证明：

```text
0 <= planned_alight <= inbound_load <= capacity
through_load = inbound_load - planned_alight
planned_alight = released_alight + not_alighted
departure_load = through_load + boarded <= capacity
```

成功发车还必须证明 `release_complete_step <= actual_departure_step`；失败 close 输出结构化
容量不足记录并禁止 successful departure。

## 4. Phase 2 — 单写者集成

### T3 — Entry publication transaction

- `DemandScheduler` 只产生 due demand；reservoir 持有所有重试状态。
- 删除 native Counter 与 Alignment unresolved/pending 双账，或暂时保留只读兼容视图。
- admission token、具体 decision/approach holding owner、source cell、movement placement 与
  Passenger 注册形成可补偿 transaction。
- 临时 full 保留 FIFO head；无效几何一次性 `model_invalid`，不无限 retry。

### T4 — Alighting 与发车截止

- 名义下车排程在 train arrival 时建立有限 manifest，ticket 绑定同一 train run。
- `train.step()` 在成功发车前调用 manifest close preflight。
- pending > 0 时设置 structured run result 并停止正常执行；不得进入后续列车。
- 每班输出 release completion、blocked steps、not_alighted、failure code 与 departure status。

### T5 — Active body backpressure

- 发布前必须预留具体的第一 body-clear owner；counting token 不是物理存储证明。
- 发布后的 `DecisionHoldingCapacityError` 保持结构化 invariant failure，不能退回 source。
- 修复当前高负荷 step 192 的 expected-capacity 硬错误，但不吞掉 invalid geometry。

## 5. Phase 3 — 指标与三门验收

### T6 — Per-boundary ledger

Entry 输出 scheduled/due/published/waiting/active/completed/dropped/conserved 与该 entrance 的
wait 分布。Train 按 run id 输出完整 manifest。只允许汇总人数守恒，不允许 entry 与 on-train
等待合并成 source-wait p50/p90/p99。

### T7 — Dynamic gate

- demand > 0、service opportunities > 0、completed > 0。
- 每 flow 的 admitted 与 completed 都必须达到 preregistered floor。
- source pending 可以大于 0，但每 tick 守恒、dropped=0、FIFO/group atomicity、liveness=0。
- Round 26 replan/placement retry 各 `<=1%`。

### T8 — Clearance gate

在 cutoff 记录每瓶颈 backlog：

```text
H_f = sum_b[L_f,b + ceil(N_f,b / mu_min_f,b)] + downstream_tail_f
```

任一 rate/latency/tail 无证据，状态为 `prediction_unavailable`，不执行“正式通过”的试探尾段。
有预测时，实际持续时间不得超过预测；终局 source/active/queue/owners 全零、守恒成立，所有
成功发车 manifest 都满足下车完成早于发车。

### T9 — Stress gate

- 欠配资源必须有正 exhaustion numerator，并仍保持 typed wait、守恒和无 dropped。
- scheduled demand、service opportunity、completion 都必须大于 0，禁止真空通过。
- expected capacity 不得未处理异常；invalid geometry 仍 fail-fast。

## 6. Phase 4 — 资格化与证据阶梯

1. 纯单元：reservoir、manifest、transaction rollback、三门计算。
2. 集成：entry blocked/recover、alighting blocked-before-close、capacity fail、invalid topology。
3. Qualification：固定窗口 `[75,315)`、`[315,555)`，seeds 41–45；blocked 时间不得剔除。
4. 冻结 empirical `mu_min` 与 tail 后，生成新的 prediction artifact。
5. Held-out：seeds 46–50；dynamic、clearance、stress 分开报告。
6. Round 26 回归：240/480 × seeds 42/43/44，replan 与 placement retry 保持退休。

## 7. 子 agent 角色与写权限

- Agent A — Reservoir Kernel：只写 reservoir 模块与纯单测。
- Agent B — Evidence/Prediction：只读推导 arrival、floor、clearance schema；不调 horizon。
- Agent C — Train Manifest：只写 manifest 模块与纯单测。
- Root — Integration Owner：唯一修改 model init、passenger demand、train lifecycle、Alignment 与门禁者。
- 最终独立 Reviewer：只读检查物理边界、守恒、真空通过、Round 26 回归和证据 SHA。

Entry integration 与 backpressure integration 必须串行，不能由两个 agent 同时修改 admission 主路径。

## 8. 完成定义

本轮只有在以下全部满足时完成：领域对象与集成已测试；动态门存在非零服务 floor；列车无跨班
pending；capacity failure 是结构化结果；clearance prediction 要么由冻结资格证据推导并 held-out
通过，要么明确保持 blocked/unavailable 而不声称 Round 27 完成；三门不真空通过；Round 26 服务链
不退化；review 与 debt delta 均落盘。
