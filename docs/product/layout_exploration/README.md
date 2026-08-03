# PM-028 布局拓扑探索验收计划

- 计划版本：`layout_exploration_plan.v1`；实现版本：`layout_exploration_acceptance.v1`
- 日期：2026-07-18
- 状态：`implemented / E1～E5 fully tested / E6 smoke+shard+resume+soak tested / nightly+release scale pending`
- 上游证据：`../PM-028_GENERATED_LAYOUT_ACCEPTANCE_EVIDENCE.md`
- 安全边界：本计划验证软件合同、拓扑一致性、仿真可复现性和展示适配性；不构成车站设计规范审查、通行能力认证、现场校准或疏散安全认证。

## 决策

下一阶段不以继续增加同类随机样本为主，而以扩大拓扑语义和失败面为主。六个试探包分别验证：

1. 异形平面、跨层链路和付费区组合能否从设计贯通到回放；
2. 几何与合同临界值能否稳定地通过或拒绝；
3. 不同客流形态与设施故障叠加时是否保持运行事实完整；
4. 非语义变形是否保持应有的不变量；
5. 场景、资产、运行设施绑定和真实浏览器是否一致；
6. 已有 nightly/release 档位能否在目标硬件上稳定运行。

## 当前实现与证据边界

| 能力 | 实际实现 | 当前证据边界 |
|---|---|---|
| 布局生成 | `constraint_layout_generator.v2` 在原4类骨架上加入 L/T/U/瓶颈、CHAIN、DUAL_CLUSTER、进出闸机分离 | 软件合同覆盖；不等于真实站型规范审查 |
| 静态门禁 | E1 64/64、E2 227/227、E4 100对 + 50敏感性注入；E6 smoke 64/64 | 旧生成器曾有2,000 nightly静态证据；v2的2,000/10,000完整档位待调度 |
| 仿真 | E3 252/252；E6 smoke 12/12；4重场景×2重复浸泡通过 | v2的150 nightly和300 release分层样本待调度 |
| 回放 | 12场景×3视口=36/36 Chromium；0/1/3/6电梯、逐层过滤、诊断、旋转和placement均受测 | 桌面2D范围，不声明移动端或3D质量 |
| 数字资产 | `asset_manifest.v1` 程序化资产及有限placement正式支持 | 外部二进制资产明确进入 PM-029 / `asset_manifest.v2`；当前未整合GLB/纹理/LOD/动画 |

## 试探包索引

| ID | 文档 | 优先级 | 规模 | 核心问题 |
|---|---|---:|---:|---|
| E1 | [拓扑形态包](TRIAL-01_TOPOLOGY_SHAPES.md) | P0 | 48个核心案例 + 16个能力探针 | 上游换拓扑后，下游是否仍合理 |
| E2 | [临界值与破坏包](TRIAL-02_BOUNDARY_AND_MUTATION.md) | P0 | 227个确定性案例 | 边界附近是否稳定、诊断是否准确 |
| E3 | [需求—故障耦合包](TRIAL-03_DEMAND_AND_DISRUPTION.md) | P1 | 12基线 + 72故障组合，3种子，共252次 | 复杂运营状态下是否保持事实完整 |
| E4 | [变形等价包](TRIAL-04_METAMORPHIC_INVARIANTS.md) | P1 | 20基例 × 5变形 = 100对 | 非语义变化是否破坏拓扑或回放 |
| E5 | [回放、资产与浏览器包](TRIAL-05_REPLAY_ASSET_BROWSER.md) | P1 | 12场景 × 3视口 | 场景/资产/运行绑定是否可靠展示 |
| E6 | [规模与浸泡包](TRIAL-06_SCALE_AND_SOAK.md) | P2 | 2,000/10,000静态 + 150/300仿真样本 | 性能、内存、分片和复现是否稳定 |

E1～E5计数已经由机器目录和统一报告核对；E6表中的 nightly/release 仍是待执行档位，不能从smoke线性外推为通过。

## 2026-07-18 实际执行摘要

- 统一结果合同：`layout_exploration_case.v1`、`layout_exploration_report.v1`、逐阶段检查和失败目录已实现；
- E1：48核心 + 16探针，64/64；E2：227/227；E3：252/252、最大人员核算误差0；
- E4：100/100变形对满足声明不变量，50/50故意注入被检测；
- E5：36/36真实Chromium运行，12张主证据图；
- E6：64静态 + 12仿真 smoke 通过；1/2/4分片规范结果一致；真实中断续跑无重复遗漏；4类重场景各2次浸泡通过；
- 统一命令输出共739个结果到 `output/layout_exploration/pm028-full-20260718-v2`；E6 smoke基线在 `output/layout_exploration/pm028-e6-smoke-v2`；
- 当前工作树为dirty，manifest已如实记录，故这些是开发工作站证据，不是冻结的release证据。

## 共同案例分类

每个案例必须在运行前声明一种预期，不允许根据运行结果反向修改分类：

| 分类 | 含义 | 门禁规则 |
|---|---|---|
| `VALID` | 当前合同明确支持 | 所有适用阶段必须通过；任一异常即失败 |
| `INVALID` | 当前合同明确禁止 | 必须在声明的最早阶段拒绝，并包含预期诊断码 |
| `STRESS` | 合同支持但负载可能超过给定时间窗 | 允许明确的 right-censored；不得崩溃、丢人、产生非有限数或无诊断降级 |
| `AUDIT` | 当前合同未决定是否支持 | 记录观察结果，不进入发布通过率；必须转成“支持并纳入VALID”或“拒绝并纳入INVALID”的产品决定 |

`AUDIT` 不是长期逃生口。每个 `AUDIT` 案例都必须记录决策负责人、决定截止条件和后续需求ID。

## 共同案例合同

实现已新增版本化探索案例合同，最小字段如下：

```json
{
  "schema_version": "layout_exploration_case.v1",
  "suite_id": "PM028-E1",
  "case_id": "E1-CORE-L-FULL-SPLIT-M0",
  "generator_version": "topology_trial_generator.v1",
  "expected_class": "VALID",
  "factors": {},
  "seed": 42,
  "expected_failure_stage": null,
  "expected_diagnostic_codes": [],
  "requirements": ["PM-028"],
  "notes": ""
}
```

同一 `case_id + generator_version + seed` 必须重建相同设计。案例目录、设计、场景、资产清单和仿真报告分别计算语义指纹，不用文件路径或生成时间参与指纹。

## 共同执行流水线

```text
case contract
  -> design generation / mutation
  -> schema + geometry + layout validation
  -> station topology compilation
  -> StationScene + runtime bindings
  -> AssetManifest + ReplayPackage
  -> journey / operation simulation (sampled)
  -> browser render (representative cases)
  -> evidence + minimized failure
```

每一阶段都必须独立出结果，不能只输出一个总布尔值：

1. `contract`：版本、单位、枚举、有限数和必填字段；
2. `layout`：尺寸、足迹、间距、队列和设施最低要求；
3. `topology`：图编译诊断、旅程可达性、跨层链路和付费方向；
4. `replay`：实体、关系、运行设施映射和资产引用；
5. `simulation`：人员守恒、终态、事件应用、确定性和right-censor；
6. `display`：真实浏览器结构断言、诊断、页面错误和截图。

## 实现边界

后续实现沿用现有正式包、testkit、acceptance和应用分层，不在生产domain里放随机语料或浏览器代码：

| 位置 | 计划职责 | 禁止事项 |
|---|---|---|
| `quality/metro_station_testkit` | 探索案例合同、确定性案例目录、拓扑生成、单变量破坏和变形操作 | 不执行HTTP/浏览器，不决定发布通过 |
| `quality/metro_station_acceptance` | 六包分阶段验收、覆盖统计、失败最小化、证据模型和Markdown报告 | 不复制生产编译器或仿真规则 |
| `packages/metro_station` | 只在 `AUDIT` 决定支持或明确拒绝后修改正式合同/校验/编译行为 | 不导入quality、tests、scripts或visualizer |
| `apps/station_visualizer` | 消费既有scene/replay/asset合同并输出展示诊断 | 不重建拓扑，不从runtime ID字符串推断owner |
| `tests` | 合同单测、针对性集成测试和真实Chromium代表场景 | 不持久化大语料快照 |
| `scripts/run_layout_acceptance.py` | 生成语料档位、稳定分片、逐案例检查点、续跑和合并 | 不承载业务判断或私有仿真实现 |
| `scripts/run_layout_exploration.py` | 编排E1～E6并写入统一探索证据 | 不复制各suite规则 |

计划模块使用领域名称，例如 `topology_trial_catalog`、`boundary_trial_catalog`、`metamorphic_invariant_report`；不创建 `utils.py`、`helpers.py` 或一个包含六类逻辑的超大模块。每个suite拥有独立案例目录和验收器，共享的只能是版本化案例合同、阶段结果和证据写入协议。

实际统一命令：

```powershell
uv run --no-sync python scripts/run_layout_exploration.py --suites e1 e2 e3 e4 e5 e6 --e3-mode full
uv run --no-sync python scripts/run_layout_acceptance.py --tier nightly --generated-profile --generated-only --shard-index 0 --shard-count 4
uv run --no-sync python scripts/merge_layout_acceptance.py <four-shard-report-json-files>
```

`--resume-from` 接受完整report或逐案例checkpoint目录；续跑会校验corpus、generator、shard算法和锁定配置指纹。

## 共同不变量

- 每个运行设施映射到且只映射到一个场景实体；一个物理实体可以拥有多个运行设施。
- 所有场景关系和资产绑定引用已存在的实体；重复ID和未知引用必须显式拒绝。
- 展示资产不得改变拓扑、容量、设施服务状态、旅客目标或仿真指标。
- 任何动态故障都必须在一个tick内进入运行事实、快照、报告和回放事件。
- 每个仿真案例保持人员守恒；非有限数、负人数和无归属运行实体一律失败。
- 相同版本、案例、种子和执行环境的语义结果可复现。
- “画出来了”只证明display truth；不得代替topology truth或simulation truth。

## 证据目录与保留策略

建议输出结构：

```text
output/layout_exploration/<run_id>/
  run_manifest.json
  coverage.json
  summary.json
  summary.md
  cases/<case_id>/case.json
  failures/<case_id>/design.json
  failures/<case_id>/diagnostics.json
  failures/<case_id>/station_scene.json
  failures/<case_id>/asset_manifest.json
  failures/<case_id>/replay_package.json
  failures/<case_id>/simulation_summary.json
  failures/<case_id>/browser.png
  failures/<case_id>/minimized_case.json
```

- 成功案例只持久化案例合同、指纹和阶段摘要；不提交成千上万个重复设计文件。
- 失败案例保留可直接复现的设计和相关下游产物。
- 最小化器依次删除装饰资产、冗余设施、无关连接和非必要需求段；只有保持相同首个失败阶段与诊断码才接受缩减。
- 浏览器金样只保留代表场景；其他截图仅在失败时保留。

## 覆盖度规则

每次报告必须列出各因子单值覆盖和二元组合覆盖。核心小矩阵直接全组合，不为48或60个案例引入覆盖数组算法。只有后续因子使全组合超过运行预算时，才先评估成熟的covering-array库；若不引入依赖，则使用可审计的固定案例表，不写不可解释的随机筛选器。

覆盖通过条件：

- 声明的每个因子值至少出现一次；
- 声明为强制的每个因子对至少出现一次；
- 分层仿真样本至少覆盖拓扑形态、跨层方式、故障类型、资产密度和电梯数量；
- `AUDIT`、`INVALID` 和 `STRESS` 不与 `VALID` 混算通过率。

## 实施和执行顺序

1. 先实现共同案例合同、分阶段报告和失败证据格式。
2. 实现并执行E1核心48例，冻结拓扑形态和跨层语义。
3. 实现E2，补齐生成器和校验器最容易漏掉的边界。
4. E1、E2稳定后实现E3；否则需求—故障结果无法归因。
5. 用E4验证测试本身对非语义变化和故意破坏是否敏感。
6. E5只选择前四包已经稳定的代表案例进入真实浏览器。
7. 最后执行E6；规模运行不得用于掩盖前面的小型确定性失败。

## 完成定义与当前判定

实现工作按以下条件判定；其中大规模执行另列状态：

- 六份试探包均有机器可读案例目录和可复现命令；
- 所有 `VALID`、`INVALID` 门禁通过，`STRESS` 无数据完整性故障；
- 所有 `AUDIT` 已形成明确支持/拒绝决定或列入带负责人和截止条件的backlog；
- E6 smoke、分片、续跑和浸泡已在当前工作站产生证据；v2 nightly/release完整规模证据仍为 `implemented / not executed`；
- 证据文档准确区分implemented、tested、demonstrated和proposed；
- 未把软件自动化结果表述为现场有效性或安全认证。

因此：六包的代码、案例、命令和自动化门禁实现完成；E1～E5以及E6 smoke/工程机制已测试通过；E6 nightly/release执行调度与PM-029外部资产合同仍是明确的后续项。
