# 对外线（Outbound Line）交接背景

- 状态：`proposed`
- 建立日期：2026-08-04
- 负责人：待填（计算机博后）
- 授权方：项目负责人
- 本文档用途：接手人上手前的完整背景，含现状、约束、已定决策和待决事项

---

## 0. 一句话

**对外线负责：把内部还在剧烈变动的仿真系统，切出可引用的版本，并以不泄露源码的方式交付给外部使用者。**

它是目前唯一有真实外部截止日期、却没有负责人的一条线。

---

## 1. 团队现状（2026-08-04 16:50 实测）

五条线，四个人在跑，一条空着。

| 线 | 负责人 | 性质 | 当前状态 |
|---|---|---|---|
| 仿真引擎 | 师兄 | **唯一在造产品的** | PM-033 实施中，未收敛 |
| 门禁与语料 | Skull Breaker | 护栏 | **已交付**，32/32 码、47 probes、0 blocked |
| 标定与证据 | 麻瓜师弟 | 证据 | 代码完成，**被主线卡住** |
| Torch 后端 | torch 师弟 | 探索 | **已交付**，结论 `limited-go` |
| **对外线** | **空** | 交付 | **两个 deadline 无人负责** |

### 1.1 师兄（仿真引擎）

- 今日已改 41 个 `packages/` 文件，昨日 83 个，前日 30 个
- 在追一类反复出现的缺陷：**乘客从走行态切换到设施服务态时，JuPedSim 放置失败**
  - 8-03 电梯 landing 动态碰撞
  - 8-04 站台 boarding holding 区 `JuPedSimPlacementBlocked`
  - `facility_closure` 场景崩溃诊断（seed42/43）
- **信号：`artifacts/acceptance/generated_geometry_full_final_v8.json`** —— "full_final" 已到 v8
- 8-03 06:33 曾经四个冻结场景四门全 PASS，随后被独立审查推翻，此后 140+ 文件改动使该证据失效
- **根本问题：完成定义是"四场景四门 PASS + 三个 agent PASS"，而代码库每天改 40–80 个文件，旧证据不断失效。他自己出不来。**

### 1.2 Skull Breaker（门禁与语料）

- 32 个编译期诊断码、47 个可执行 control/mutant 探针、41 个 emitter site 全覆盖、0 blocked
- `status: Literal["active"]` 从类型层面禁止"声明不可达"逃逸
- **已完成，当前空闲**

### 1.3 麻瓜师弟（标定与证据）

- Eindhoven 站台数据 1.85 亿行入 canonical，PedPy 管线打通，137 个测试通过
- **被主线卡死**：正式 10 分钟运行需要 Metro 代码指纹稳定，但师兄每天改几十个文件，多次运行被指纹门拒绝；最近一次执行到第 327 步被 `JuPedSimPlacementBlocked` 中断
- 状态：`code_complete / implementation_hold / calibration_hold`

### 1.4 torch 师弟（探索）

- 真实 Jülich 数据、吞吐 1.34e6 vs 基线 9.98e5、四选一判据给出 `limited-go`
- **已交付，等一句决策**（冻结标定线还是继续）
- 遗留：8 个 evidence 目录并存，权威版本不明确

---

## 2. 项目最大的结构性问题

**没有版本。**

```
HEAD                91be25b (8-03 09:25)
未提交               341 M / 38 D / 167 ??
tag                 无
release 分支         无
```

`apps/`、`docs/architecture/`、`docs/sdk/`、`experiments/`、`examples/` 整棵树仍未跟踪。

直接后果：

- 麻瓜师弟拿不到稳定基线 → 整条标定线停摆
- 学弟只能拿到"某天的 HEAD"，不是可引用的东西
- 大赛演示没有确定的东西可展示
- 出问题无法二分定位

**这是对外线要解决的第一个问题，也是唯一能同时解开三个人死结的动作。**

---

## 3. 两个外部截止日期

### 3.1 学弟上线（约 4 天）

外校研究者要用这个环境做**地铁疏散路由算法**研究。

**硬约束：不能给他看 `packages/metro_station/` 源码。**

原因：不同学校、无共同机构约束、项目有商业化意图。私有仓库不可行（clone 后撤权限也收不回）。

### 3.2 创业大赛（日期待定）

需要向评委展示"有服务能力"。

**红线**：当前 `CalibrationProfile.status = "uncalibrated"`，alignment 报告 `candidate_not_validated`，自由流速度误差 −19.2%（阈值 15%），基本图落带率 0%。

**不能声称**：能预测疏散时间、可用于安全评估或消防审查。
**可以声称**：算法研究与方案比较平台、同环境同种子的可复现相对比较、已有外校研究者使用。

---

## 4. 已经定下的决策（不要推翻重议）

### 4.1 交付方式：我们跑，学弟不跑

学弟拿到的四样东西，**全部零 IP**：

| 内容 | 状态 |
|---|---|
| 拓扑 JSON | 需导出（数据，非代码） |
| 协议文档 | 已有 `docs/sdk/EVACUATION_ROUTING_PLUGIN.md` |
| 示例插件 | 已有 `examples/evacuation_routing_plugin/`，纯标准库，`imports no metro-station modules` |
| 独立协议校验器 | **需新写**，几百行，只做 JSON schema 与路径合法性检查 |

流程：学弟提交 `plugin.py` → 我们跑 → 回传裁剪过的指标 JSON。

**已排除的方案及原因：**

- **私有仓库**：等于给源码，不可逆
- **PyInstaller / 编译分发**：保护强度弱（可解包反编译）、触发 JuPedSim LGPL 分发义务、四天打不完、主线每天在变导致包立刻过期
- **等 PM-033 收尾再发**：不可控

### 4.2 运行环境

负责人常出差、不常开机，**必须有一台常开的机器**。两个候选：

| 方案 | 成本 | 优势 | 劣势 |
|---|---|---|---|
| 阿里云轻量 2核2G | ¥68/年 | 装一次依赖永久解决、可 ssh 调试 | 需偶尔运维 |
| GitHub Actions | 免费（私有仓库 2000 分钟/月） | 零运维、天然沙箱 | 依赖缓存配置麻烦 |

**推荐先用阿里云 300 元免费试用（4核8GiB，3 个月）实测**，拿到真实内存峰值和耗时后再决定买哪档。

**资源实测依据**：`evac_100`（100 人、405 秒）产出的 102 MB replay 中，98.1 MB 是逐帧快照（406 帧 × 0.15 MB），`movement_trace` 仅 4 MB。**关掉快照输出后峰值内存约 300–400 MB，2 GB 足够。**

**最大风险不是算力，是依赖安装** —— `jupedsim`、`shapely`、`pyarrow` 全是原生扩展。**第一件事就是在 Linux 上试装。**

### 4.3 三个信息泄露口子（必须堵）

1. **回传内容要裁剪** —— 只回聚合指标，不回 `simulation_trace`（含字段名、事件类型、诊断码，等于送出数据模型）
2. **错误信息要脱敏** —— traceback 含完整模块路径和文件结构，统一包装成自定义错误码
3. **`validate-routing-plugin` 输出同样过滤**

### 4.4 反向风险：学弟代码在我们机器上跑

`docs/sdk/EVACUATION_ROUTING_PLUGIN.md` 自己写着：

> 这是批次完整性隔离，**不是针对不可信代码的安全沙箱**；只运行经过审查的本地插件。

不同学校的提交者属于不完全可信来源。**必须沙箱化**：Docker 容器、断网、只读挂载拓扑输入、非 root、**源码放容器外**。

这不是可选项。没有它，前面所有保密努力归零。

### 4.5 许可证

JuPedSim 是 **LGPL-3.0-or-later**。

- 我们自己跑、不分发二进制 → **义务基本不触发**
- 一旦分发（哪怕只给一个人）→ 触发：附许可证文本、提供源码获取途径、允许替换重链接

这是选择"我们跑"而非"发 exe"的又一个理由。商业化前需请专业人士过一遍完整依赖树。

---

## 5. 学弟要用的接口（好消息：这块很稳）

**插件 SDK 全链路冻结在 07-16，19 天未动**：

```
application/routing_plugins/    contracts / manifest / execution / topology / validation
adapters/routing_plugins/       baseline / registry / process_host / contract_suite
interfaces/cli.py               metro-station 命令入口
docs/sdk/EVACUATION_ROUTING_PLUGIN.md
examples/evacuation_routing_plugin/
```

**师兄这几天 140+ 文件的改动几乎没有波及这一面。** 唯一被碰到的是下游的 `evacuation_journey_rerouting.py`。

协议形态很干净：独立子进程 + stdin/stdout 单行 JSON，`api_version: evacuation-routing/v1`，10 个契约案例，退出码 0 表示全过。

---

## 6. 一个必须先跑的实验（发版硬门槛）

**验证环境是否真的在执行插件的决策。**

做法：写一个**故意绕远路**的算法（边成本取反或强制最长路），跟内置基线同种子跑。

- 清场时间显著变差 → 环境在执行插件决策，学弟的相对比较有意义
- 清场时间基本没变 → **环境忽略了插件，学弟做什么都白做，不能发版**

BACKLOG 里已有这条要求（"不同战略路由插件必须能够产生不同 portal 路线和可观察轨迹"），但没有证据显示它被验过。

**半小时能跑完，结论是二元的。建议排在所有工程工作之前。**

同时要测出**环境噪声 σ**：同一算法跑三个种子的波动。这个数字必须交给学弟——它决定了"多大的改进才算真改进"。

---

## 7. 职责边界

### 做

| 职责 | 具体 |
|---|---|
| 版本与发布 | 切 release、定冻结窗口、维护变更日志与已知限制清单 |
| 学弟交付 | 拓扑导出、独立校验器、跑批脚本、运行环境 |
| 信息边界 | 输出裁剪、错误脱敏、插件执行沙箱 |
| 大赛材料 | 预跑结果、演示脚本、叙事的事实核对 |

### 不做（明确排除）

- 不改 `packages/metro_station/` 的实现
- 不接手 PM-033
- **不做架构重构**

最后一条最重要。熟悉代码的人接手容易先"理一理架构"，但对外线的价值在四天内出东西。

---

## 8. 授权（需项目负责人确认后生效）

**一、有权要求主线冻结。**

可宣布"某时间点起 N 小时冻结 `packages/`"，师兄必须配合。

这条是必需的：师兄的完成定义在一个每天改几十个文件的代码库上永远达不到，**只能靠外部时间盒打破**。他自己下不了这个决定——PM-033 第 7 节明确写着"任何未解决硬失败都必须保留为失败，不得降级成已知限制"。这条纪律在收尾阶段是对的，但在还没有基线时会阻止拿到任何基线。

**二、有权决定对外暴露什么。**

裁剪回传内容、脱敏错误、决定给学弟看什么，不必逐次请示。

**三、无权改仿真实现。**

这条是保护，避免被拖进 PM-033。

---

## 9. 建议的第一周

| 天 | 任务 | 完成标志 |
|---|---|---|
| 1 | 通读现状；与师兄、三位师弟各聊 30 分钟；与负责人确认授权 | 清楚三条支撑线各卡在哪 |
| 2 | **宣布并执行第一次冻结** | 有 `v0.1.0` tag；麻瓜师弟的 10 分钟 v5 跑完；已知限制清单成文 |
| 3 | 绕远路对照实验 + 环境噪声 σ；Linux 依赖试装 | 二元结论；装机可行性确认 |
| 4–5 | 学弟交付：拓扑导出 + 校验器 + 跑批 + 沙箱 + 运行环境 | 学弟能提交插件并拿到结果 |
| 6 | 大赛材料事实核对 | 每句话可指到证据 |

**第 2 天的冻结是关键。** 拿出 tag 就立住了；拿不出来，对外线还是空的。

冻结的具体做法建议：

> 宣布某时刻起 4 小时冻结 `packages/`。这 4 小时内跑完四个冻结场景、跑完 alignment 的 10 分钟运行、记录结果。**过不了的项目记为"已知失败"写进文档，不阻塞打 tag。**

---

## 10. 待决事项（需要负责人给答案）

1. **创业大赛具体日期** —— 决定优先级排序
2. **torch 师弟的 `limited-go` 结论**：冻结还是继续
3. **接手人的动机** —— 对外线通常不产出论文。若需要学术产出，有一条现成方向：arXiv:2605.11633（DORA）建立了宏观地理尺度的灾害响应 agent 评测基准，**建筑内部尺度是空白**，而我们的插件 SDK + 四道质量门 + 确定性种子恰好是这类评测所需的基础设施
4. **与学弟的书面约定** —— 跨校合作，需明确成果署名、商业化意图、算法权属

---

## 附录 A：关键路径速查

```
插件协议规范      docs/sdk/EVACUATION_ROUTING_PLUGIN.md
示例插件          examples/evacuation_routing_plugin/
CLI 入口          packages/metro_station/src/metro_station/interfaces/cli.py
协议契约          packages/metro_station/src/metro_station/application/routing_plugins/
进程宿主          packages/metro_station/src/metro_station/adapters/routing_plugins/process_host.py
权威轨迹          packages/metro_station/src/metro_station/adapters/simulation/movement/trajectory_trace.py
四道质量门        quality/metro_station_acceptance/src/metro_station_acceptance/
编译期诊断        packages/metro_station/src/metro_station/adapters/simulation/compilation/
标定线            alignment/README.md
对抗语料          quality/metro_station_testkit/CORPUS_ADVERSARIAL_PLAN.md
主线计划          docs/product/PM-033_COMPLEX_PEDESTRIAN_TRAJECTORY_PLAN.md
产品 Backlog      docs/product/BACKLOG.md
```

## 附录 B：绝对不能对外说的话

- 「我们能预测疏散时间」
- 「可用于安全评估 / 消防审查 / 数字孪生」
- 「参数已标定」
- 「端到端打通了点云 → 客流 → 仿真」（点云能力当前不存在）
- 「我们用社会力模型」（默认跑的是 `collision_free_speed`；社会力在支持列表内但未作为基线验证）

## 附录 C：可以且应该说的话

- 「算法研究与方案比较平台，支持第三方接入自己的疏散路由算法」
- 「同站型、同需求、同种子的可复现相对比较」
- 「32 个编译期设计诊断，每个都有可执行反例证明它会在该失败时失败」
- 「4 道轨迹质量门；系统会主动拒绝自己没验证的结论」
- 「已有外校研究者接入使用」
- 「参数标定进行中，当前明确标注为未标定，只支持相对比较」
