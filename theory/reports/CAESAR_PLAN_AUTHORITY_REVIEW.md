# 凯撒治国计划：基于权威文献的评价

评价日期：2026-08-02  
评价对象：[凯撒治国计划架构提案](../sources/CAESAR_PLAN_2026-08-02.md)  
文件性质：非正式立法研究；不是法律、合规裁定、校准报告或工程验收。  

## 总结评价

**总体判定：`partially supports`——可作为实验平台总览，但尚不能作为行为科学架构定稿。**

这份计划最成熟的是“如何组织一次可复现的仿真实验”：站型输入、案例版本、任务编排、隔离运行、指标、回放和报告形成了完整产品链。它最薄弱的是“旅客行为为何如此发生”：战略活动、战术路线/设施选择、局部导航、操作运动和实证验证的权威边界仍不够清楚。

更准确地说，凯撒已经画出了**实验国家的行政机构**，但还没有完整写清**旅客行为的权力分立与科学证据链**。

| 评价维度 | 结论 | 含义 |
|---|---|---|
| 实验平台结构 | **绿：支持** | 分层交互、版本化实验、批量/配对运行、报告与回放方向与 13、15、16 相容 |
| 站内领域覆盖 | **黄：部分支持** | 需求、设施、列车、队列和指标均已出现，但若干过程只列名、未明确行为合同 |
| 行为分层 | **红：存在实质冲突** | “活动”同时位于 AgentPlan 生成与战术决策；局部导航也未从操作运动中明确分出 |
| 模型身份 | **红：表述不成立** | `JuPedSim / Social Force` 混合执行引擎、模型家族与实际激活模型 |
| 校准与验证边界 | **红：混淆** | 在线指标、观测数据、校准和独立验证被一条箭头合并 |
| 科学有效性 | **证据不足** | 架构图不能证明参数已校准、行为已验证或具有跨站预测能力 |
| 工程与发布就绪 | **不由文献判断** | API、数据库、Worker、格式和恢复机制属于工程选择，需要工程证据而非论文背书 |

## 采用的权威链

本评价不把 17 篇论文等权使用。

| 角色 | 权威来源 | 在本评价中的用途 | 证据状态 |
|---|---|---|---|
| 站内领域总纲 | [02 Daamen (2004)](../notes/02_daamen_passenger_flows.md) | 战略—战术—操作分层；设施、队列、服务、列车与指标 | 全文核验 |
| 混合导航蓝图 | [03 Kneidl et al. (2013)](../notes/03_kneidl_hybrid_multiscale.md) | 图导航、局部导航场、微观运动和动态成本反馈 | 全文作者稿核验 |
| 模块化架构 | [15 Curtis et al. (2016)](../notes/15_curtis_2016_menge.md) | Goal、Plan、Plan Adaptation、环境查询、事件与观察职责 | 全文核验 |
| 实测闭环范例 | [16 Nishida et al. (2023)](../notes/16_nishida_2023_route_choice_real_data.md) | 战术 DCM—操作模型解耦、重复实验、留出验证与系统误差 | 全文预印本核验 |
| 当前运动模型血缘 | [17 Tordeux et al. (2015)](../notes/17_tordeux_2015_collision_free_speed.md) | Collision-Free Speed 的能力和失效边界 | 全文预印本核验 |
| 站—车—数据闭环 | [13 Hanseler et al. (2020)](../notes/13_hanseler_2020_passenger_pedestrian.md) | AFC/列车数据、乘客身份、站台与车厢联动、独立观测 | 全文核验 |

辅助来源包括动态重路由 [04](../notes/04_kemloh_wagoum_dynamic_route_choice.md)、原始 SFM [09](../notes/09_helbing_molnar_1995.md) 和多层寻路验证 [14](../notes/14_feng_2022_vr_wayfinding.md)。01、06、08、11、12 只有摘要/元数据证据，只用于方向性结论，不用于公式、参数或效应量。

## 逐层证据评价

判定使用 `supports / partially supports / contradicts / not enough information / not applicable`。

| 计划部分 | 判定 | 权威依据 | 评价 |
|---|---|---|---|
| 教师、学生、研究人员、运营人员作为并列用户 | `not enough information` | 文献不是用户研究；本地[产品愿景](../../docs/product/PRODUCT_VISION.md) | 文献能支持运营分析场景，不能证明四类用户共享同一工作流。当前产品证据只把教师、学生、算法研究者列为首要用户，运营人员是次要用户 |
| 网页站型设计器 | `partially supports` | [02](../notes/02_daamen_passenger_flows.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md) | 文献支持楼层、区域、连接、设施类型、方向、能力和可用状态等语义；不支持“网页”这一技术选择，也不证明设计器可用性 |
| 实验配置器：需求、列车、控制、随机种子 | `supports`（概念层） | [13](../notes/13_hanseler_2020_passenger_pedestrian.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 与数据驱动输入、时刻/容量、控制条件及随机重复实验相容；随机种子只是复现清单的一部分 |
| 二维分析、轨迹、密度、排队和热力图 | `supports`（输出层） | [02](../notes/02_daamen_passenger_flows.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md)、[14](../notes/14_feng_2022_vr_wayfinding.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 输出方向合理，但动画与热力图只是观察工具，不能替代量化验证 |
| Unity 三维回放 | `not applicable` 于行为合法性 | [14](../notes/14_feng_2022_vr_wayfinding.md)、[15](../notes/15_curtis_2016_menge.md) | 14 研究的是 VR 行为数据采集，不是三维回放有效性；15 将 motion synthesis 与行为模型分开。Unity 只能是展示客户端，不能成为第二仿真引擎或验证证据 |
| API、数据库、文件格式和 Worker | `not applicable` 于学术背书 | 这些论文不规定技术栈 | 可作为工程选择，但不能用人群仿真论文证明 HTTP、SQLite、Parquet、取消或恢复语义正确 |
| 案例、版本、批量与配对实验 | `supports` | [15](../notes/15_curtis_2016_menge.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 15 支持保持其余条件不变后替换单个模块；16 支持重复运行、基线比较和模型级/系统级误差。具体版本系统仍属工程实现 |
| “模型校验：Schema、几何、拓扑、语义、参数” | `contradicts` 其术语 | [02](../notes/02_daamen_passenger_flows.md)、[08](../notes/08_robin_antonini_bierlaire_cruz_2009.md) | 这里进行的是输入与场景完整性校验。类型、范围或拓扑合法不等于行为模型得到现实验证 |
| 站型编译器 | `partially supports` | [03](../notes/03_kneidl_hybrid_multiscale.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md)、[15](../notes/15_curtis_2016_menge.md) | 文献支持图、空间区域、接口能力、局部导航空间的分离表达；不指定某种编译流水线 |
| 需求与 AgentPlan：OD、到达、活动、属性 | `supports` | [01](../notes/01_hoogendoorn_route_choice.md)、[02](../notes/02_daamen_passenger_flows.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md) | OD、到达、旅客属性、活动链和跨站/车旅程均有依据；01 只有摘要证据，不能据此批准具体活动效用式 |
| “战术决策层：活动、路径、设施、车门与重规划” | `contradicts` | [01](../notes/01_hoogendoorn_route_choice.md)、[02](../notes/02_daamen_passenger_flows.md)、[15](../notes/15_curtis_2016_menge.md) | 活动目的、活动序列和终止条件属于战略层；路线、设施、车门与重选属于战术层。当前写法把战略重新塞回战术层，并与 AgentPlan 形成双重活动权威 |
| 图路径与连续运动的分离 | `partially supports` | [03](../notes/03_kneidl_hybrid_multiscale.md)、[15](../notes/15_curtis_2016_menge.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 计划已区分 Decision 与 Locomotion，但没有明确 `全局路线/中间目标 -> 局部方向或期望速度 -> 可行运动` 的交接；这是 03 和 15 最关键的结构之一 |
| “JuPedSim / Social Force” | `contradicts` 作为模型身份 | [09](../notes/09_helbing_molnar_1995.md)、[17](../notes/17_tordeux_2015_collision_free_speed.md)、[现有设计调研](CODE_DESIGN_AUDIT.md) | JuPedSim 是执行引擎，SFM 是一种模型家族；当前默认血缘是 CFS。若 SFM 只是候选，不能与激活模型用斜杠混写 |
| 设施过程引擎 | `partially supports` | [02](../notes/02_daamen_passenger_flows.md)、[06](../notes/06_daamen_level_changes.md) | 显式设施与服务过程符合领域总纲；但闸机/安检、楼梯、扶梯和电梯具有不同的运动、服务、方向和排队语义，不能只因同属“设施”而用一种抽象吞平 |
| 列车与站台过程 | `partially supports` | [02](../notes/02_daamen_passenger_flows.md)、[12](../notes/12_seriani_2015_boarding_alighting.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md) | 到发、开关门、候车与上下车必须存在；还应保证乘客身份/数量跨站台—门区—车厢守恒，并输出门区过程指标。12 仅为摘要/highlights 证据，不能提供通用参数 |
| Kernel 与 WorldState | `partially supports`（架构推论） | [02](../notes/02_daamen_passenger_flows.md)、[15](../notes/15_curtis_2016_menge.md) | 统一时间和运行事实有利于组合多过程，但论文不直接规定一个可变 `WorldState`。图中四个双向写者没有说明事实权威、同刻冲突和提交顺序，不能仅凭“唯一事实源”解决 |
| WorldState 单向产生指标与快照 | `partially supports`（架构推论） | [15](../notes/15_curtis_2016_menge.md) | 15 支持模块职责分离，但没有直接规定本图的数据流；“观察/展示不成为权威状态所有者”是据其模块化原则形成的工程推论。若指标反馈控制，必须成为显式、有时刻和信息边界的控制输入 |
| 外部 OD、AFC、列车和观测数据 | `supports`，但用途必须拆分 | [13](../notes/13_hanseler_2020_passenger_pedestrian.md) | 13 明确区分 AFC/列车跟踪等模型输入与独立流量/密度验证观测。AFC 也可能需要推断才能形成 OD，不能与 OD 无条件等同 |
| `SOURCE -.校准与验证.-> METRIC` | `contradicts` | [02](../notes/02_daamen_passenger_flows.md)、[08](../notes/08_robin_antonini_bierlaire_cruz_2009.md)、[13](../notes/13_hanseler_2020_passenger_pedestrian.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 在线指标只计算仿真输出；估计/校准数据、独立验证观测、校准流程和验证比较器必须在概念上分开。将观测连到指标不等于完成校准或验证 |
| 报告与“可复现包” | `partially supports` | [15](../notes/15_curtis_2016_menge.md)、[16](../notes/16_nishida_2023_route_choice_real_data.md) | 控制变量、重复运行、模型规格和误差记录有依据；仅生成文件不等于可复现，仍需输入/模型/参数/环境/随机流/失败信息的完整清单 |

## 五个必须纠正的核心问题

### 1. 活动权威重复

Daamen 明确把活动目的放在战略层；Hoogendoorn & Bovy 把活动、地点和路线联立讨论；Menge 又把 Goal selection 与 Plan computation 分开。图中 `DEMAND/AgentPlan` 已生成活动，而 `DECISION` 又拥有活动，构成最明显的双权威。

安全表述应当是：战略层拥有活动目的、序列和终止条件；战术层只在给定战略目标下选择路线、设施、车门及是否重选。

### 2. 缺少局部导航这一明确交接层

Kneidl 的核心不是“有一张图加一个微观模型”，而是图、局部导航场和微观运动之间的双向合同；Menge 同样区分 plan computation 与 plan adaptation。当前图从战术决策直接跳到 Locomotion，容易让运动引擎同时承担目标生成和避碰。

本评价不规定如何实现，但架构语义必须说明：谁产生全局路线，谁把路线变成局部目标/期望方向，谁只负责生成可行运动。

### 3. 操作模型没有实名

Helbing & Molnár 只能支持实际启用的 SFM；Tordeux et al. 才是当前默认 CFS 家族的直接理论来源。写成 `JuPedSim / Social Force` 既没有区分引擎与模型，也隐藏了默认、可选和实际激活状态。

### 4. 在线指标不是校准器或验证器

Daamen 区分实现验证与现实验证；Hanseler 把 AFC/列车数据作为输入，把独立流量和密度作为验证观察；Nishida 同时报告选择模型性能与下游时序误差。图中的一条虚线把这些不同活动压成了同一件事。

### 5. `WorldState` 的唯一性仍不充分

“唯一事实源”只解决了事实放在哪里，没有解决谁能改变哪项事实、同一仿真时刻如何结算、指标是否会消费行为随机流，以及异常恢复是不是同一次运行。该问题主要是由 15 的模块边界原则和跨过程组合要求推导出的工程架构判断，不应伪装成某篇行为论文的直接结论。

## 指标覆盖评价

当前列出的密度、延误、排队、冲突和清场时间不够覆盖文献要求。

| 指标族 | 来源 | 当前图 |
|---|---|---|
| 旅行、等待和服务时间 | 02、13 | “延误”过于含糊 |
| 路线/设施/车门选择份额 | 02、06、16 | 未列出 |
| 队列长度、设施吞吐和服务能力 | 02、13 | 仅有队列，缺吞吐与能力 |
| 局部密度、流量和速度—密度关系 | 02、11、13 | 只列密度 |
| 逐门上下车人数、Passenger Service Time、未登乘 | 12、13 | 未列出 |
| 站台和车厢负载 | 13 | 未列出 |
| 决策点选择、路径效率、错误转向、犹豫/搜索 | 14 | 未列出 |
| 战术选择留出误差与下游分时计数误差 | 08、16 | 未列出 |
| 运动模型典型现象及已知失败 | 09、11、17 | 未列出 |

其中 11、12 只有摘要级证据；具体清单、阈值和效应量仍需全文或其他一手实验来源，不能直接写成固定参数。

## 产品与科学边界

### 产品价值

从“设计—配置—运行—分析—导出”的旅程看，计划完整且适合离线教学与方法研究平台。四类用户并列则过宽：权威论文不等于用户采用证据；本地产品愿景也只把教师、学生和算法研究者列为首要用户。

### 仿真可信度

架构具备产生证据的条件，但没有证据表明行为、参数或站级输出已经可信。Nishida 的案例也只是对已观测事件的复现改进，不是跨站、跨年预测证明；Hanseler 的数据驱动模型也不是在线状态同化。

### 工程就绪

论文无法评价 HTTP、数据库、文件格式、Worker 恢复或具体前端的工程就绪。架构图描述的是 `proposed` 状态；任何 `implemented / tested / calibrated / validated / transferable` 主张必须另有对应证据。

## 最终结论

这份计划可以安全地称为：

> **“一个受权威文献启发、面向离线教学与方法研究的分层仿真实验平台架构提案。”**

它目前不能安全地称为：

- 已按 Hoogendoorn/Daamen 完成完整活动—路线行为模型；
- 已按 Kneidl 完成图—局部导航—微观运动闭环；
- 已实现或校准 Logit/DCM；
- 默认采用并验证 Social Force；
- 已完成校准与独立验证；
- 已形成数字孪生；
- 已具备真实运营或安全决策能力。

因此，评价不是“推翻凯撒计划”，而是：**保留实验平台骨架，要求其在概念图上先纠正权威层级、模型实名和证据闭环，才能作为科学架构定稿。**

## 引用审计边界

- 全文级主要依据：02、03、04、09、13、14、15、16、17。
- 摘要/元数据级辅助依据：01、06、08、11、12。
- 01 不支持具体效用公式；06 不支持清单中的示意系数；08 不支持未核验的估计细节；11 不支持未经全文核验的完整现象清单；12 不支持通用 PST 参数或效应量。
- 所有“应如何组织软件”的表述均明确视为跨文献工程推论，而不是论文逐字规定。
