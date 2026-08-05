# 01 · 契约：JobSpec v0.1

> **状态：v0.1-frozen（2026-08-05）。** 后续改字段名、类型或语义必须追加 CHANGELOG。
> 修订依据：2026-08-05 师兄评审 P0-1 / P0-4。变更见文末 CHANGELOG。

---

## 适用范围（重要）

**这是 single-user limited pilot 的契约，不是生产 SaaS 契约。**

- 产品承诺与默认上限：**50 total agents**。目标机实测后才可上调至 100/200。
- 不支持真实高峰客流（数千 agent）。那需要 `metro_station` 内部改成流式 frame 导出，不在 v0.1 范围。
- `docs/product/RELEASE_REVIEW.md` 中 V0.2 发布决定仍为 **hold**。本服务不构成云端生产能力的证明。

---

## 设计原则：白名单，不是透传

底层仿真命令有 30 多个参数，其中若干是 `Path` 类型。**绝不允许把用户输入拼进命令行。**
JobSpec 是显式白名单，未列出的字段一律拒绝（pydantic `extra="forbid"`）。

排除清单见文末。

---

## 时长语义（P0-1 修订）

> **旧版有 bug**：同时有 `minutes` / `demand_minutes` / `clearance_minutes` 三个字段，
> 而 `cli.py:270-273` 实际算的是 `total = max(minutes, demand + clearance)`，
> 假 runner 算的是 `minutes + clearance`。同一份 spec 两个 runner 时长不同。

**新方案：两个权威字段，clearance 是派生量。**

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `horizon_minutes` | int | `10` | `1 ≤ x ≤ 60`。**总仿真时长**，唯一权威 |
| `demand_minutes` | int | `10` | `1 ≤ x ≤ horizon_minutes`。需求生成时长 |

```
clearance_minutes = horizon_minutes - demand_minutes      # 派生，不是输入
```

映射到底层：

```python
StationSandboxScenario(
    minutes=horizon_minutes,
    demand_minutes=demand_minutes if demand_minutes != horizon_minutes else None,
)
```

这与 `make_scenario()` 的输出一致，且**不存在 max() 造成的语义歧义**。

`clearance_minutes` 作为只读派生值出现在 `resolved_spec` 和 `summary.json` 里，请求体里出现它 → 400。

---

## 完整字段表

`spec_version` 必填，其余可选走默认。

### 元信息

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `spec_version` | str | —— | **必填**，只接受 `"0.1"` |
| `label` | str \| null | `null` | ≤ 64 字符，原样回显，批量扫描时认领结果用 |

### 场景

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `station` | str | `"小寨"` | 必须在 catalog 中。**决定站型与设施布局，不决定客流量** |
| `hour` | int | `18` | `0 ≤ x ≤ 23` |
| `design_template` | str | `"visual_demo_station"` | 必须在 catalog 中 |
| `scenario_mode` | enum | `"operations"` | `operations` \| `evacuation` |

### 时长

见上节。`horizon_minutes`、`demand_minutes`。

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `tick_seconds` | int | `1` | **只接受 1**。留字段为 v0.2|

### 客流（P0-4 修订：改为必填）

> **旧版有 bug**：默认 `null` 表示「用该站该时段真实客流」，真实值只有
> `load_station_hour_profile()` 拿得到，**API 层无法在提交时估算 agent 数**，容量闸门算不出来。
>
> **新方案**：pilot 场景本来就是人为构造的小规模，真实客流（数千人/小时）根本用不上。
> 三个字段改**必填**，API 层直接算得出 agent 数。

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `entry_count_hour` | int | **必填** | `0 ≤ x ≤ 6000` |
| `exit_count_hour` | int | **必填** | `0 ≤ x ≤ 6000` |
| `transfer_count_hour` | int | **必填** | `0 ≤ x ≤ 6000` |
| `group_size` | int | `1` | `1 ≤ x ≤ 10`。一个 agent 代表几个人 |
| `admins` | int | `0` | `0 ≤ x ≤ 50` |

运营模式下三者不得同时为 0；疏散模式下三者必须全为 0。

**50 人场景怎么填**：跑 10 分钟、只有进站客流 →
`entry_count_hour = 300`（300/小时 × 10/60 小时 = 50 人），`exit=0`，`transfer=0`。

### 疏散模式专用

仅 `scenario_mode == "evacuation"` 时生效；`operations` 下必须为默认值，否则 400。

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `initial_platform_persons` | int | `0` | `0 ≤ x ≤ 500` |
| `alarm_delay_seconds` | float | `0.0` | `0 ≤ x ≤ 600` |

疏散模式要求 `initial_platform_persons > 0`，且必须能被 `group_size` 整除。疏散
scheduler 不消费常规 entry/exit/transfer 流量。

### 引擎

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `movement_backend` | enum | `"jupedsim"` | `jupedsim` \| `batched_jupedsim` \| `micro_jupedsim` |
| `jupedsim_model` | enum | `"collision_free_speed"` | `collision_free_speed` \| `anticipation_velocity` \| `social_force` |
| `clock_mode` | enum | `"physical"` | `physical` \| `legacy_scaled` |
| `routing_algorithm` | enum | `"builtin_shortest_path"` | `builtin_shortest_path` \| `internal_graph` |

### 复现与输出

| 字段 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `seed` | int | `42` | `0 ≤ x ≤ 2^31-1` |
| `trajectory_sample_seconds` | int | `1` | `1 ≤ x ≤ 60`。**服务端后处理下采样，不传给仿真** |

---

## 完整示例（50 人场景）

```json
{
  "spec_version": "0.1",
  "station": "小寨",
  "hour": 18,
  "design_template": "visual_demo_station",
  "scenario_mode": "operations",
  "horizon_minutes": 15,
  "demand_minutes": 10,
  "tick_seconds": 1,
  "entry_count_hour": 300,
  "exit_count_hour": 0,
  "transfer_count_hour": 0,
  "group_size": 1,
  "admins": 0,
  "initial_platform_persons": 0,
  "alarm_delay_seconds": 0.0,
  "movement_backend": "jupedsim",
  "jupedsim_model": "collision_free_speed",
  "clock_mode": "physical",
  "routing_algorithm": "builtin_shortest_path",
  "seed": 42,
  "trajectory_sample_seconds": 1,
  "label": "pilot-50p-s42"
}
```

最小请求：

```json
{"spec_version": "0.1", "entry_count_hour": 300, "exit_count_hour": 0, "transfer_count_hour": 0}
```

---

## submitted_spec vs resolved_spec（P0-4 修订）

**必须同时记录两份**，否则既无法限流也无法复现。

| | 内容 | 存哪 |
|---|---|---|
| `submitted_spec` | 用户提交的 JSON 对象，规范化存储；不承诺保留空白与键顺序 | SQLite `submitted_spec` |
| `resolved_spec` | 填充默认值 + 派生量 + runner 实际使用的解析值 | SQLite `resolved_spec_json`、`summary.json` |

`resolved_spec` 比 `submitted_spec` 多出来的：

```json
{
  "...": "全部字段填充默认值后",
  "_derived": {
    "clearance_minutes": 5,
    "horizon_seconds": 900,
    "estimated_passenger_agents": 50,
    "estimated_total_agents": 50,
    "catalog_version": "0.1.0"
  }
}
```

复现一次实验 = 拿 `resolved_spec` 里除 `_derived` 外的部分重新提交。同版本、同 seed
要求科学语义与内容 fingerprint 一致；不承诺 Parquet 元数据、压缩字节或 wall time 字段一致。

API 的 `GET /v1/jobs/{id}` 两份都返回。

---

## 校验规则

按顺序，**一次性返回所有错误**（保留 pydantic 默认行为）。

1. `extra="forbid"` —— 未知字段直接拒绝。特别是 `minutes`、`clearance_minutes` 这两个旧字段名，出现即 400 并提示改用 `horizon_minutes`
2. 类型与区间
3. 跨字段：
   - `demand_minutes ≤ horizon_minutes`
   - `operations`：`entry + exit + transfer > 0`
   - `operations` 模式：`initial_platform_persons == 0` 且 `alarm_delay_seconds == 0.0`
   - `evacuation`：三个流量字段全为 0，`initial_platform_persons > 0` 且能被 group_size 整除
4. catalog 存在性：`station`、`design_template`
5. 容量闸门

### 容量闸门

```python
if scenario_mode == "operations":
    passenger_agents = sum(
        round(flow * demand_minutes / 60 / group_size)
        for flow in (entry, exit, transfer)
    )
else:
    passenger_agents = initial_platform_persons // group_size
estimated_total_agents = passenger_agents + admins
```

**纯算术，不查任何外部数据**——这正是把客流字段改必填换来的。
逐流 `round` 镜像 `StationSandboxScenario.entry_groups/exit_groups/transfer_groups`；不能先
合计再 ceil，否则混合客流会与真实 scheduler 的 agent 数不一致。非零流量若最终舍入为
0 agent，同样返回 400。

| 闸门 | 默认阈值 | 在哪 | 超了怎样 |
|---|---|---|---|
| `horizon_minutes ≤ 60` | 字段约束 | API | 400 `invalid_spec` |
| `estimated_total_agents ≤ METRO_MAX_AGENTS` | **50**（首发）；200 待 spike | API | 400 |
| 墙钟超时 | 暂定 14400 秒，目标机 spike 后收紧 | worker | 杀进程组，job → `failed` |
| 峰值内存 | systemd `MemoryMax`，**由尖峰实测决定** | systemd | worker 被杀并重启，job → `failed` |

> ⚠️ 后两行的数字**在尖峰跑完前都是猜的**。不要对外承诺。

---

## catalog

`station` / `design_template` 的合法值数据驱动，后端不硬编码。

```
apps/cloud_api/data/catalog.json
```

```json
{
  "catalog_version": "0.1.0",
  "spec_version": "0.1",
  "stations": ["小寨", "钟楼", "北大街"],
  "design_templates": ["visual_demo_station"]
}
```

**不需要客流解析值**——客流字段已改必填（这是 P0-4 修订带来的简化）。

开发期后端自造假 catalog；联调时 gen 换成真的。

---

## 排除清单

| 参数 | 为什么排除 |
|---|---|
| `--goal-graph-config` | `Path` 类型 → 路径注入 |
| `--routing-plugin-manifest` | 同上，且属 v0.2 自定义算法 |
| `--tracks-out` / `--replay-json-out` / `--bundle-json-out` / `--out` | `Path` 类型，输出位置由服务端决定 |
| `--routing-parameters-json` | 自由 JSON，难校验，v0.2 放开 |
| `--routing-timeout-seconds` / `--routing-run-timeout-seconds` | 服务端资源管控，用户调它 = 绕过闸门 |
| `--no-audit` | 诊断开关，服务端恒开 |
| `minutes` / `clearance_minutes` | **已被 `horizon_minutes` / `demand_minutes` 取代**，出现即 400 |

**规则**：任何 `Path` 或自由格式 JSON，v0.1 一律不进白名单。

---

## CHANGELOG

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-08-05 | 0.1-draft-1 | 初稿 |
| 2026-08-05 | 0.1-draft-2 | 师兄评审修订：<br>· **P0-1** `minutes`/`clearance_minutes` → `horizon_minutes`/`demand_minutes`，clearance 改派生<br>· **P0-4** 客流三字段改必填，容量闸门变纯算术；catalog 不再需要客流解析值；新增 submitted/resolved 双记录<br>· 规模上限从 50000 降到 500（pilot）<br>· 标注 limited pilot 定位与 RELEASE_REVIEW hold 状态 |
| 2026-08-05 | 0.1-frozen | 真实 runner 本机 25/50/100/200 四档尖峰和 50 人 HTTP E2E 通过；冻结字段、默认值、纯算术容量闸门与 submitted/resolved 双记录。目标机尖峰只决定部署上限，不再改变本契约。 |
