# 02 · 契约：产物与 Schema

> **状态：v0.1-frozen（2026-08-05）。** 后续改字段名、类型或语义必须追加 CHANGELOG。
> 修订依据：2026-08-05 师兄评审 P0-3 / P0-6。变更见文末 CHANGELOG。

---

## 文件布局

```
/data/jobs/{job_id}/
├── trajectories.parquet     成功时必有
├── events.parquet           成功时必有（可能 0 行）
├── summary.json             成功/失败/取消都必有 ← P0-6
└── run.log                  必有
```

**`summary.json` 不由 runner 写**：执行过的 job 由 worker 写；尚未执行就取消的 queued
job 由 API 写同构 summary（P0-6 修订，见下）。

**后端同学**：除了 `07-integration.md` 的契约校验脚本，不要解析 parquet 内容。你只负责建目录、传给 runner、列文件、提供下载。

---

## trajectories.parquet（P0-3 重写）

> **旧版有 bug**：我发明了一个 `phase` 字段，但 `runtime/snapshots.py:28-40` 的
> `PassengerSnapshot` **根本没有 `phase`**。真 runner 无从产出。
>
> **新方案**：每一列都必须能指到源码里的一个真实字段。下表「来源」列就是这个证明。

一行 = 一个 agent 在一个采样时刻的状态。

| 列 | Arrow 类型 | 可空 | 来源 |
|---|---|---|---|
| `agent_id` | `int32` | 否 | `PassengerSnapshot.id` |
| `t_seconds` | `float32` | 否 | `FrameSnapshot.time_seconds` |
| `x` | `float32` | 否 | `PassengerSnapshot.x` |
| `y` | `float32` | 否 | `PassengerSnapshot.y` |
| `group_size` | `int32` | 否 | `PassengerSnapshot.n` —— **一个 agent 代表几个人** |
| `state` | `dictionary<string>` | 否 | `PassengerSnapshot.state` = `AgentState` |
| `intent` | `dictionary<string>` | 否 | `PassengerSnapshot.intent` = `AgentIntent` |
| `goal_kind` | `dictionary<string>` | 是 | `PassengerSnapshot.goal["kind"]` = `AgentGoal.kind` |
| `goal_stage` | `dictionary<string>` | 是 | `PassengerSnapshot.goal["stage"]` = `FacilityStage` |
| `goal_facility_id` | `dictionary<string>` | 是 | `PassengerSnapshot.goal["facility_id"]` |
| `level_id` | `dictionary<string>` | 是 | `PassengerSnapshot.current_level_id` |
| `platform_id` | `dictionary<string>` | 是 | `PassengerSnapshot.platform_id` |

`group_size` 那一列很关键：`group_size > 1` 时，统计人数必须 `df.group_size.sum()` 而不是 `df.agent_id.nunique()`。SDK 文档要写清楚。

### 枚举取值（`domain/passengers/states.py`）

这三个是 domain 层的 `StrEnum`，受 import-linter 保护，取值稳定：

**`state`** —— `AgentState`，16 值：

```
entering_station    queueing_gate         passing_gate           walking_to_vertical
queueing_vertical   riding_vertical       walking_to_platform    waiting_capacity
waiting_platform    queueing_door         boarding_train         walking_to_exit_gate
queueing_exit_gate  passing_exit_gate     walking_to_transfer    departed
```

**`intent`** —— `AgentIntent`，4 值：

```
enter_and_board    exit_station    evacuate_station    transfer
```

**`goal_stage`** —— `FacilityStage`，4 值 + null：

```
entry_gate    vertical_transfer    boarding_door    exit_gate
```

`goal_kind` 是自由字符串（`AgentGoal.kind`），当不透明值处理。

> **不要在后端或 SDK 里硬编码这些枚举做校验。** 列出来是给用户看的。
> 源码里同一份文件还定义了 `WALKING_STATES` / `PASSIVE_STATES` / `SERVICE_STATES` 分组，
> 用户想要聚合可以自己按上表分类，我们不额外出列。

**排序**：`agent_id` 升序，同 agent 内 `t_seconds` 升序。
**压缩**：`zstd` level 3。
**行数量级**（pilot 50 人）：50 agent × 900 秒 ÷ 1 秒采样 ≈ 4.5 万行 ≈ **1 MB 以内**。

> 规模小是 pilot 的刻意选择。旧版按数千 agent 设计的「体积压力点」章节已删除——
> 在 50 人量级下，`Range` 下载和保留策略降级为「有就行」，不是设计约束。

---

## events.parquet（P0-3 修订）

> **旧版有 bug**：假设一行一个 agent，但 `facilities/service_events.py:15` 的
> `FacilityServiceEvent.passenger_ids` 是 `tuple[int, ...]` —— **一个服务事件可能涉及多个乘客**
>（一次电梯载多人、一次开门多人上车）。

**新方案：按 `passenger_ids` explode 成逐 agent 行，保留 `event_id` 让用户能重新分组。**

| 列 | Arrow 类型 | 可空 | 来源 |
|---|---|---|---|
| `event_id` | `string` | 否 | 命名空间 ID：`facility:<source_id>` 或 `terminal:<agent>:<index>` |
| `agent_id` | `int32` | 是 | `passenger_ids` 中的一个。null = 非乘客事件 |
| `t_seconds` | `float32` | 否 | `start_time` |
| `end_seconds` | `float32` | 是 | `end_time` |
| `event_type` | `dictionary<string>` | 否 | 见下 |
| `facility_id` | `dictionary<string>` | 是 | `FacilityServiceEvent.facility_id` |
| `facility_kind` | `dictionary<string>` | 是 | `FacilityServiceEvent.facility_kind` |
| `party_size` | `int32` | 是 | `len(passenger_ids)`。**该 event 共涉及几个 agent** |
| `detail_json` | `string` | 是 | 其余字段的 JSON：`mode`/`direction`/`from_level`/`to_level`/`commit_time`/`board_end_time`/`arrive_time` |

`event_type` 的来源：

| 值 | 来自 |
|---|---|
| `facility_service` | `FacilityServiceEvent` |
| `passenger_terminal` | `PassengerTerminalEvent`（乘客旅程终止记录；该源码类型没有 event_id） |

用户想还原「一次电梯载了哪些人」：`df.groupby("event_id").agent_id.apply(list)`。

`detail_json` 是刻意的逃生舱口——不同设施类型带的字段不同，硬拉平会变成宽表噩梦。

**排序**：`t_seconds` 升序，同 t 内 `event_id` 升序。
允许 0 行，但空表也要写出文件且带完整 schema。

---

## summary.json（P0-6 修订）

> **旧版有协议冲突**：契约要求失败时也有 `summary.json`，但只有 runner 会写它——
> 而 runner 挂了就不会写。
>
> **新方案：`summary.json` 一律由 worker 写。**

职责划分：

| 谁 | 写什么 |
|---|---|
| **runner** | `trajectories.parquet`、`events.parquet`、`_result.json`（一个只含 `result` 段的小文件） |
| **worker** | 读 `_result.json`（存在且有效则用，否则填固定 null 字段），拼上 job 元信息、timing、error，写出 `summary.json`，然后删掉 `_result.json` |
| **API** | queued job 尚未进入 worker 就被取消时，立即写同一固定结构的 `summary.json`；此时 runner 与 started/wall 字段为 null |

worker 存活时会在 finally 写 summary。若 worker 自身被 SIGKILL 或 cgroup 杀死，finally
不会执行；worker 重启恢复会为所有遗留 running job 补写 `worker_lost` summary。

```json
{
  "schema_version": "0.1",
  "job_id": "3f2a9c1e-...",
  "status": "succeeded",

  "submitted_spec": { "...用户原样提交的..." },
  "resolved_spec":  { "...填充默认值 + _derived..." },

  "runner": { "kind": "real", "version": "0.1.0" },

  "timing": {
    "created_at": "2026-08-20T09:59:58Z",
    "started_at": "2026-08-20T10:00:00Z",
    "finished_at": "2026-08-20T10:04:31Z",
    "wall_seconds": 271.4
  },

  "result": {
    "passenger_agent_count": 50,
    "admin_agent_count": 0,
    "total_agent_count": 50,
    "person_count": 50,
    "simulated_seconds": 900.0,
    "trajectory_rows": 44100,
    "event_rows": 312,
    "clearance_seconds": 782.0,
    "coordinate_transform": "identity_meters",
    "peak_rss_bytes": 412876800
  },

  "error": null
}
```

- `status`：`"succeeded"` \| `"failed"` \| `"cancelled"`
- `runner.kind`：`"fake"` \| `"real"`。**联调时靠这个确认换对了**
- `result.person_count`：每个唯一 passenger agent 的 group_size 之和；管理员不计入
- `result.clearance_seconds`：全部 agent 离场时刻；未清空则 `null`
- `result.peak_rss_bytes`：worker 从子进程测得。**尖峰要靠它定 `MemoryMax`**
- `error`：失败时 `{"kind": "...", "message": "...", "detail": "..."}`

`error.kind` 取值：

| 值 | 含义 |
|---|---|
| `runner_exception` | runner 抛异常 |
| `nonzero_exit` | 子进程非零退出 |
| `timeout` | 超过 `METRO_JOB_TIMEOUT_SECONDS`，进程组被杀 |
| `memory_limit` | worker 的进程树 RSS 采样超过软闸门 |
| `worker_lost` | worker 被强杀或重启；没有证据时不猜测为 OOM |
| `worker_error` | worker 自身出错 |
| `invalid_artifact` | runner 退出 0，但 Parquet schema、行数、排序或计数契约不成立 |
| `missing_artifact` | runner 退出 0，但缺少必要产物 |
| `cancelled` | queued job 在执行前取消，或 running child 已按取消请求终止 |

失败或取消时 `result` 里的计数、时长和坐标变换字段全为 `null`，但**键必须存在**
（避免用户代码 `KeyError`）；若 child 已启动，实测 `peak_rss_bytes` 可以保留。queued
取消没有 `started_at`，因此 `timing.wall_seconds` 为 `null`。

---

## 契约测试

假 runner 和真 runner 的产物必须通过**同一个**校验函数，见 `07-integration.md` 的
`assert_output_contract()`。这是并行开发能成立的关键。

---

## CHANGELOG

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-08-05 | 0.1-draft-1 | 初稿 |
| 2026-08-05 | 0.1-draft-2 | 师兄评审修订：<br>· **P0-3** 删除编造的 `phase` 列，改为 `state`/`intent`/`goal_kind`/`goal_stage`/`goal_facility_id`，每列标注源码出处；补 `group_size`、`platform_id`<br>· **P0-3** events 表按 `passenger_ids` explode，新增 `event_id`/`party_size`/`facility_kind`/`end_seconds`<br>· **P0-6** `summary.json` 改由 worker 写，runner 只写 `_result.json`；新增 `error.kind` 枚举<br>· 新增 `submitted_spec`/`resolved_spec` 双记录、`peak_rss_bytes`<br>· 按 50 人 pilot 规模重估体积，删除旧的「体积压力点」章节 |
| 2026-08-05 | 0.1-frozen | 真实 runner 本机四档尖峰、50 人 HTTP E2E、10×50 soak 及 Fake/Real 同构校验通过；冻结两份 Parquet schema、事件展开语义和固定结构 summary。补明 queued 取消由 API 写 summary，以及失败/取消的 null 字段、`wall_seconds`、`cancelled`/`missing_artifact`。目标机尖峰只决定部署上限。 |
