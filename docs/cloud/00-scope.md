# 00 · 范围与分工

> **定位：single-user limited pilot。**
> `docs/product/RELEASE_REVIEW.md` 中 V0.2 的发布决定仍为 **hold**，首要用户和发布门禁
> 仍是本地教学/算法实验。本服务是一次单用户试点，**不构成云端生产能力的证明**，
> 也不改变 V0.2 的 hold 状态。对外一律称 "limited pilot"。

## 目标

一句话：**用户用 Python 提交一批参数化仿真，拿回可直接分析的 parquet 轨迹。**

```python
from metro_cloud import Client

with Client("http://127.0.0.1:8000") as c:  # SSH 隧道
    job = c.submit({
        "station": "小寨", "hour": 18,
        "horizon_minutes": 15, "demand_minutes": 10,
        "entry_count_hour": 300, "exit_count_hour": 0, "transfer_count_hour": 0,
        "seed": 42,
    })
    job.wait()
    job.download("trajectories.parquet")
job.wait()
df = job.trajectories()                       # -> pandas DataFrame
print(df.groupby("state").agent_id.nunique())
```

这段代码在部署好的服务器上跑通，v0.1 就算达成。

---

## 规模约束（决定了整个设计）

**产品承诺与部署默认上限：50 total agents。200 只作为目标机 spike 候选。**

这不是保守，是让项目可行的关键约束：

| 如果按数千 agent 设计 | 50 人 pilot |
|---|---|
| `run()` 把全部 frames 攒在内存，数千 agent 风险不可接受 | 本机 25-agent 预检 RSS 约 660 MiB；50 人仍须目标机实测，不能写“绰绰有余” |
| 必须给 `MetroStationModel.run()` 加流式 `frame_sink`，改动 `metro_station` 包内部 | **不用改仿真包** |
| 产物几十到上百 MB，`Range` 下载和保留策略是硬约束 | Fake 约 100 KB/job；真实体积待测，Range 与 2 GiB 保留预算已实现 |

> 换句话说：**50 人这个约束替我们砍掉了 v0.1 最大的一块工程风险。**
> 想支持真实高峰客流，需要先做 frame 流式导出，那是 v0.2 的事。

---

## 定位：批量实验跑批服务

不是「算法平台」。用户提交的是**参数**，不是代码。

真实价值有两条：

1. **免装环境** —— 用户不用在自己机器上装 mesa + JuPedSim。这大概是最实在的一条。
2. **批量扫描** —— 20 个 seed × 若干配置，云上串行跑完，不占本地机器。

> 用户已知悉：v0.1 不能跑他自己写的路由算法，那是 v0.2。

---

## 非目标（v0.1 明确不做）

| 不做 | 理由 |
|---|---|
| 用户注册/登录/用户表/权限 | 1 个用户 |
| 用户认证系统、HTTPS 公网入口 | 通过 SSH 隧道访问；可选 token 只做纵深防御 |
| 容器/gVisor 沙箱 | 不运行用户代码；worker 仍使用 systemd cgroup 资源闸门 |
| 上传自定义算法代码 | v0.2 |
| 计费、配额 | 1 个用户 |
| Web 前端 | 站型设计器继续做本地工具 |
| 对象存储 S3/OSS | 服务器本地目录 |
| Celery / Redis / RabbitMQ | 单机单 worker + SQLite 够了 |
| K8s、自动扩缩容 | 一台固定 ECS |
| 可视化 replay 产物 | 用户用途是指标分析，不需要渲染 |
| 多 worker 并发 | v0.1 串行跑。设计上不排斥，但不实现 |

**看到「要不要顺手把 X 也做了」的念头，先回来看这张表。**

---

## 分工边界

```
┌─────────────────────────────────────┐
│  后端同学的地盘   apps/cloud_api/    │
│                                     │
│  · FastAPI 服务（8 个端点）          │
│  · SQLite job 存储                  │
│  · worker 进程 + 进度 + 超时         │
│  · 产物下载 + 磁盘清理策略           │
│  · 客户端 SDK metro_cloud            │
│  · 部署脚本 + systemd               │
│                                     │
│  依赖：fastapi uvicorn pydantic      │
│        pandas pyarrow httpx         │
│  禁止：import metro_station          │
└─────────────────────────────────────┘
              ▲
              │  SimulationRunner 协议（唯一接缝）
              ▼
┌─────────────────────────────────────┐
│  gen 的地盘                          │
│                                     │
│  · 真 runner：调 metro-station        │
│  · frames -> parquet 导出器          │
│  · 场景/模板校验数据                 │
└─────────────────────────────────────┘
```

后端同学**不需要**：

- 安装 mesa / jupedsim（很重，装起来麻烦）
- 跑 `uv sync --all-packages`
- 理解站型、客流、寻路、Goal Graph 是什么
- 读 `packages/metro_station/` 下任何代码

后端同学**需要**：Python 3.12、`uv`、能读懂 `01`/`02`/`03` 三份契约。

---

## 名词表

后端同学只需要认识这几个词，其余仿真术语一律当作**不透明字符串**处理。

| 词 | 对后端而言是什么 |
|---|---|
| **JobSpec** | 一个 JSON 对象，用户的请求参数。字段定义见 `01` |
| **Job** | 一次仿真任务。有 id、状态、进度、产物目录 |
| **Runner** | 一个可调用对象，输入 JobSpec 和输出目录，产出文件。见 `04` |
| **产物 / artifacts** | job 跑完落在 `output_dir` 里的几个文件。见 `02` |
| **station** | 站点名，中文字符串。合法值由服务端一张列表校验，不需要理解含义 |
| **design_template** | 站型模板 id，英文字符串。同上 |
| **tick** | 仿真的一步，v0.1 固定 1 秒 |
| **frame / snapshot** | 仿真每一 tick 的全场快照。**只有真 runner 内部用到，后端不接触** |
| **agent** | 仿真里的一个（组）乘客。一个 agent 可能代表多人，见 `group_size` 列 |
| **state / intent** | 乘客状态与出行意图，来自 domain 层 `StrEnum`。后端当 category 字符串处理，**不硬编码枚举** |

---

## 时间线（15 个工作日）

> **旧版按 20 个工作日排，是错的。** 2026-08-05（三）到 08-25（二）含首尾
> 只有 **15 个工作日**。下表是重排后的结果。

| 日期 | gen | 后端同学 |
|---|---|---|
| 8/05 三 | **尖峰 1**：in-process `executor.execute()` 跑通 1 分钟仿真 | 环境 + 目录骨架 |
| 8/06 四 | **尖峰 2**：产出两份 parquet、过契约测试、测 5/15/30 分钟峰值内存 | JobSpec model + 校验 |
| 8/07 五 | **尖峰评审 → 契约冻结**；SDK 假数据版交付用户 | SQLite store |
| 8/10 一 | 真 runner 正式实现 | 假 runner + `child.py` 接入 |
| 8/11 二 | 真 runner | worker 主循环 |
| 8/12 三 | 真 runner；catalog 换真数据 | worker 超时 / 进程组 / 崩溃自愈 |
| 8/13 四 | 真 runner 过契约测试 | FastAPI 端点 |
| 8/14 五 | **交付真 runner** | FastAPI + 路径穿越/Range 测试 |
| 8/17 一 | 联调 1 | 联调 1 |
| 8/18 二 | 联调 2 + 容量表填完 | 产物管理 + 保留策略 |
| 8/19 三 | 支援 | SDK |
| 8/20 四 | 支援 | SDK |
| 8/21 五 | 部署上云 | 部署上云 |
| 8/24 一 | 用户试用 | 修 bug |
| 8/25 二 | **交付** | 缓冲 |

### 8/25 承诺什么

| 承诺 | 不承诺 |
|---|---|
| 50 人量级场景端到端跑通 | 60 分钟真实高峰客流 |
| 单次 job 提交 → 轮询 → 下载 → `read_parquet` | 数千 agent |
| 批量 10 个 job 串行跑完 | 80 个 job 的批量压测 |
| SDK 核心方法（submit / wait / trajectories / events / summary） | SDK 本地缓存与断点续传（降级为 nice-to-have） |
| 失败路径正确（超时、异常、非零退出都能拿到 `summary.json`） | 稳定运维、告警、监控 |
| `runner.kind` 可查，随时能回退到 `fake` | 任何 SLA |

**这张表是对师兄工期质疑的正式回应**：15 天做「假 runner 全链路 + 真 runner 小场景试点」有希望，
同时承诺高峰场景 + 完整压测 + 稳定运维则风险很高，所以后者明确不承诺。

### 两个不能挪的节点

1. **8/07 尖峰评审**。尖峰不过，`01`/`02` 不冻结，后端不进入 D4 以后的任务。
   尖峰的头号问题不是「能不能产出 parquet」，而是 **5/15/30 分钟场景的峰值内存到底是多少**。
2. **8/07 交付 SDK 假数据版给用户**。他写分析脚本和我们建服务并行，
   他会在第一周告诉我们 parquet 少了哪一列。这个反馈晚一周就要返工。
