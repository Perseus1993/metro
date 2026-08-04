# 立法调研：现有算法设计观察

审计日期：2026-08-02  
审计对象：`packages/metro_station/` 正式仿真包及其相关质量探针  
审计边界：只读审计；未修改生产实现、运行配置或测试。

文件性质：非正式立法研究。代码与测试只作为观察材料；本文不作合规裁定，不执行校准或验收，也不构成开发计划、接口设计任务或工程指令。

## 结论

当前系统最值得保留的是分层架构，最需要补的不是另一套“更复杂的力”，而是行为选择的可估计性、默认运动模型的准确血缘、跨层动态成本反馈和独立实测验证。

另有一项工程观察：本次定向回归的 23 个测试中，12 个通过、3 个失败、8 个在装配阶段报错。失败集中在垂直设施队列入口槽预留和登乘微场景的列车容量接口。该事实说明算法比较必须满足共同、稳定基线，因而支持 L-012；如何修复不属于本文或元老院职能。

## 当前真实结构

```mermaid
flowchart LR
    A["Journey / Goal Graph<br/>活动意图与设施阶段"] --> B["Facility selector<br/>确定性最小广义成本"]
    B --> C["StationGraph / routing plugin<br/>静态图路径与关闭边"]
    C --> D["Physical route<br/>同层几何路径与目标点"]
    D --> E["JuPedSim operational model<br/>默认 CollisionFreeSpeed"]
    B --> F["Facility process<br/>排队、闸机、楼扶梯、电梯、车门"]
    E --> F
    F --> G["队长、服务率、局部密度、故障事件"]
    G --> B
```

这个结构已经与“战略/战术/操作”分层、混合图导航和模块化仿真的文献方向相容，但“结构相容”不等于“参数有效”或“预测已验证”。

## 已经做对的部分

### 1. 战略目标与物理目标有明确边界

`Goal Graph` 是唯一战略权威，`AgentPlan` 只是短期物理目标适配器；终止事件也受 Goal 命令约束。该设计与 Hoogendoorn & Bovy 的多时间尺度思想及 Menge 的模块化思想相容。证据见：

- `docs/architecture/ADR-002-goal-authority.md`
- `packages/metro_station/src/metro_station/domain/goals/`
- `packages/metro_station/src/metro_station/adapters/simulation/planning/plan.py`

边界：默认 Journey 是预制的线性活动链，不是经行为模型产生的活动日程。当前最多可称“活动链执行器”，不能称“已实现活动调度理论”。

### 2. 四类算法接口没有混成万能插件

策略选择、疏散路由、局部运动和实验优化被明确拆开，V0.2 只产品化路由插件。这个决定有利于实验归因，也与 Kneidl 的混合分层和 Menge 的可替换模块一致。证据见 `docs/architecture/ADR-007-layered-algorithm-extension-ports.md`。

### 3. 设施选择已有可审计的成本分解和重选迟滞

当前选择器显式记录步行、偏好、引导、回避、排队、服务和密度成本，并具有承诺期、冷却期和最小改善阈值。相比固定分流比例，这已经是重要进步。证据见：

- `packages/metro_station/src/metro_station/domain/goals/choice.py`
- `packages/metro_station/src/metro_station/adapters/simulation/runtime/passenger_goal_observation.py`
- `packages/metro_station/src/metro_station/domain/goals/facility_reducer.py`

边界：这是确定性的最小成本规则，不是已估计的离散选择模型。

### 4. 局部运动引擎可替换且轨迹可留证

正式运行时把连续运动交给持久 JuPedSim session，并保留轨迹、模型时步和丢失/恢复诊断。当前默认 `jupedsim_operational_model` 是 `collision_free_speed`；适配器也支持 `social_force`，但它不是默认值。证据见：

- `packages/metro_station/src/metro_station/adapters/simulation/station/scenario.py`
- `packages/metro_station/src/metro_station/adapters/simulation/movement/backend.py`
- `packages/metro_station/src/metro_station/adapters/simulation/movement/jps_adapter.py`

### 5. 未校准边界写进了合同

`CalibrationProfile` 区分 `uncalibrated / calibrated / validated`，并要求校准集和验证集独立。这一诚实边界应保留。证据见 `packages/metro_station/src/metro_station/adapters/simulation/calibration/`。

## 主要理论差距

| 层 | 当前实现 | 文献要求或合理主张 | 审计判断 |
|---|---|---|---|
| 战略活动 | 四类固定 intent 映射到预制 Journey Graph | 活动目的、活动次序、时机和约束可被建模 | 架构就位，行为模型缺失 |
| 战术设施选择 | 确定性最小广义成本 | 候选集、随机效用、个体异质性、参数估计与样本外验证 | 核心升级点 |
| 垂直设施选择 | 偏好罚时、疲劳、排队与服务时间 | 高差、上下行、设施类型、绕行和乘客属性的可估计效用 | 部分实现，系数无证据 |
| 全局路径 | StationGraph 边成本主要来自二维距离；插件接收关闭边 | 动态旅行时间/拥堵成本、感知范围、信息和重路由触发 | 静态路径强，动态反馈弱 |
| 局部导航 | JuPedSim 对连续几何和目标负责 | 图—局部导航场—微观运动的明确合同及反馈 | 实现上可用，理论合同未显式化 |
| 操作层 | 默认 CollisionFreeSpeed，可选 SocialForce | 模型身份、实现版本、参数来源和典型现象验证 | 模型身份需纠偏，验证不够 |
| 上下车 | 列车 `away/boarding`、固定停站、容量、车门服务和下车生成 | 开门—下车—冲突—上车—关门过程及服务时间/局部密度指标 | 有骨架，过程仍过度聚合 |
| 校准 | 清场时间和峰值局部密度的 MAE/MAPE 门限 | 选择模型估计、轨迹校准、过程指标和独立样本外验证 | 证据面过窄 |
| 数据同化 | AFC/客流仓库与仿真包分离 | AFC、列车跟踪和现场观测更新隐藏状态 | 尚未实现，不能称数字孪生 |
| Wayfinding | 拓扑路径和轨迹 | 错误转向、犹豫、搜索时间、路径重合和熟悉度差异 | 尚未验证 |
| 大规模混合 | 活跃乘客均进入微观运动 | 网络分配与局部微观仿真的多尺度切换 | 暂未实现，是否需要取决于性能证据 |

## 两个必须纠正的学术表述

### “我们用的是社会力”目前不准确

默认配置是 `collision_free_speed`。因此，Helbing & Molnar (1995) 可以作为操作层模型史和可选 SFM 的原始基线，但不能单独为默认运行背书。默认模型应首先引用 Tordeux, Chraibi & Seyfried (2015)，并记录 JuPedSim 版本及实际参数。

若切换到 JuPedSim `social_force`，还必须说明该实现使用哪些 SFM 版本和默认参数；仅更换字符串不构成校准或验证。

### “我们已经用了 Logit”目前不准确

生产 Goal 选择器调用 `MinimumPerceivedCostSelector`，按最小总成本确定性选择。`facility_choice_logit_sensitivity` 只在场景参数中声明，没有进入生产选择器；`pick_logit` 的实际调用位于可视化轨迹模块，而非正式 Goal 选择路径。当前最多可说“代码库有 Logit 抽样函数原型”，不能说“生产路径选择已实现并估计 MNL”。

## 当前回归证据

执行命令：

```text
uv run --no-sync pytest -q \
  tests/test_facility_generalized_cost.py \
  tests/test_runtime_evacuation_routing_plugin.py \
  tests/test_goal_boarding_probe.py \
  tests/test_calibration_validation.py \
  tests/test_official_metro_station_package.py
```

结果：`12 passed, 3 failed, 8 errors`。

- 3 个失败：`tests/test_runtime_evacuation_routing_plugin.py`；垂直设施预留槽被判定为非 approach slot。
- 8 个错误：`tests/test_goal_boarding_probe.py`；`GoalBoardingMicroScene` 缺少 `train_capacity_for_platform`。
- 广义成本、校准合同及正式包边界的其余选定测试通过。

这只是当前工作区的工程行为证据，不是实测有效性证据。

## 立法影响

上述观察不产生工程任务，只说明若干通用法律具有必要性：

| 设计观察 | 支持的现行法律 |
|---|---|
| Goal、设施选择、路由和局部运动已经分层，但行为主张仍可能越界 | L-001 三层分权法；L-002 唯一权威法 |
| 默认模型是 CollisionFreeSpeed，而 SocialForce 只是可选项 | L-003 模型实名法；L-009 运动模型边界法 |
| 正式设施选择为确定性最小成本，Logit 原型未进入正式路径 | L-006 候选集完整法；L-007 随机效用实名法 |
| 设施层具有动态成本，图层动态感知范围仍不完整 | L-008 动态信息有界法 |
| 上下车过程存在骨架，但部分交互和指标仍聚合 | L-010 站台—车门守恒法 |
| AFC/客流仓库与仿真分离，没有在线状态更新闭环 | L-011 数据闭环实名法 |
| 当前定向测试基线不稳定 | L-012 模块比较同条件法 |
| 当前校准证据主要集中在少数汇总指标 | L-004 参数来源法；L-005 校准—验证分离法 |

具体怎样实现、校准、测试、修复或验收，由 Theory 之外的责任体系决定。本文到此停止，不给出工程路线图。
