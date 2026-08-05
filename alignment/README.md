# Alignment：开放行人数据对齐与参数标定

- 状态：`code_complete / implementation_hold (source geometry model_invalid) / calibration_hold`
- 建立日期：2026-08-03
- 负责人：待填
- 主线影响：**无**。本目录独立 venv、独立依赖，不进 uv workspace，不进 Import Linter。

---

## 0. 这份文档是给谁看的

给第一次接触这个项目、需要独立把「开放行人数据 → 对齐 → 标定我们的仿真参数」这条链路跑通的人。

假设你：

- 会写 Python，用过 pandas
- **没有**读过 `packages/metro_station/` 的代码
- **不需要**读懂 JuPedSim 或 Mesa

不懂的名词看第 2 节。卡住超过半天就问，别硬扛。

---

## 1. 我们要解决什么问题

### 1.1 现状

仿真里有一批参数是「拍脑袋」定的。打开 `packages/metro_station/src/metro_station/adapters/simulation/station/scenario.py`，能看到：

```python
jupedsim_desired_speed_mps: float = 1.2
escalator_speed_units_per_tick: float = 2.3
stairs_speed_units_per_tick: float = 1.55
stairs_preference_share: float = 0.18
stair_fatigue_cost_up: float = 0.6
stair_fatigue_cost_down: float = 0.15
stair_bidirectional_conflict_factor: float = 0.3
gate_service_persons_per_min: int = 55
```

这些数字**没有文献或观测来源**。仓库自己也承认这一点——`calibration/contracts.py` 里 `CalibrationProfile` 的默认状态就是：

```python
profile_id = "default_uncalibrated"
status = "uncalibrated"
notes = "Default parameters have not been calibrated against station observations."
```

论文里如果被问「这个 1.2 m/s 哪来的」，现在答不上来。

### 1.2 我们做什么

下载公开的真实行人轨迹数据，用标准工具算出观测值，跟仿真跑出来的值对照，给每个参数一个有出处的建议值。

```
公开数据集  →  统一格式  →  PedPy 算指标  ┐
                                          ├→  对照报告  →  参数建议
仿真 movement_trace → 统一格式 → PedPy 算指标 ┘
```

关键设计：**观测和仿真走完全同一套分析代码**。这样比出来的差异才是真差异，不是两套算法的差异。

### 1.3 我们不做什么

- **不验证 JuPedSim 本身**。它的运动模型在文献里已经验证过了，重做没有学术价值。
- **不做轨迹级的逐点比对**。我们比的是统计量（速度分布、基本图、流量），不是「第 37 号乘客走的曲线像不像」。
- **不改主线任何代码**。

---

## 2. 名词表

| 名词 | 意思 |
|---|---|
| **轨迹 / trajectory** | 一个人随时间的位置序列，`{id, t, x, y}` |
| **基本图 / fundamental diagram** | 行人流研究的核心图：横轴密度（人/m²），纵轴速度或流量。人越挤走越慢，这条曲线描述了这个关系。是这个领域的「黄金标准」 |
| **自由流速度 / free-flow speed** | 周围局部隔离、几乎无相互作用时的步行速度。当前实现只有“低全局密度 + 速度截断”的代理，不能等同于这个概念 |
| **通行能力 / capacity** | 单位时间单位宽度最多能过多少人。楼梯、通道、闸机各有设计值 |
| **标定 / calibration** | 用观测数据调模型参数，让模型输出贴近观测 |
| **验证 / validation** | 用**没参与标定**的另一批数据检验模型。标定集和验证集必须独立，否则是自欺欺人 |
| **PedPy** | Jülich 研究中心出的开源 Python 库，专门算上面这些指标。MIT 协议 |
| **canonical 格式** | 我们自己定的统一轨迹格式。所有数据集先转成它，后面分析只写一遍 |
| **movement_trace** | 仿真产出的**权威**轨迹（`movement_trace.v1`），0.2 秒一个采样点 |
| **visual_tracks** | 仿真产出的**表现层**轨迹。里面约 19% 的点是为了好看插值伪造的（`visual_only: true`）。**绝对不要用它做分析** |

---

## 2. 当前执行状态（2026-08-04）

- Canonical 已改为严格六列契约：空值、坏 ID、额外列、重复时间和非有限数均硬失败；Eindhoven days 01–10 已重建为 185,234,516 行，`dataset_id` null=0，并完成全量单调时间与速度量级校验。
- 观测与仿真统一走 PedPy `individual speed + classic density + frame mean speed`；双方强制匹配 PedPy 版本、`0.4s` 物理速度窗口、过滤阈值、分箱和共享测量多边形 hash，任一不同即 `unavailable`。
- Metro seam 接受裸 `movement_trace.v1` 和官方 `simulation_trace.v1` wrapper，只取显式 `phase=walking`；`(passenger_id, episode_id)` 通过稳定 BLAKE2b 映射进入 signed-int64 仿真命名空间，子集/全量运行保持同一 ID，碰撞则硬失败；不落采样网格的时间在 PedPy 前拒绝。
- `platform_boarding` 编译自己的参数化 DesignDocument；它仍是 Eindhoven bbox 尺寸代理而非完整实景复刻。窄走廊/瓶颈受 Metro 主线最小设施几何约束，明确为 pending。
- 当前 observed v5 从完整数据确定 5 个源帧号和源时间都连续的完整帧窗；199,806 行、4,909 个真实帧进入 PedPy。速度代理实际贡献 102,075 点/806 agent/4,909 帧/5 窗，p50=1.169 m/s；基本图实际贡献 199,806 点/890 agent/4,909 帧/5 窗。大/小数据路径都校验可信 frame rate，遇到稀疏帧只会截断或拒绝，不再压紧并伪造速度。
- Step 6 是独立科学门：低全局密度步行速度代理误差必须 `<=15%`；基本图需同时满足支持覆盖 `>=80%`、至少 3 个双方 `n>=30` 的重叠箱且覆盖到 `>0.3 人/m²`、条件落带 `>=80%`。任何 unavailable/outside 均保持 calibration hold。
- Metro 正式工件同时记录完整 SceneConfig schema/hash、设计 hash、原始 trace/canonical hash，以及 Metro 源树、Python、关键依赖和 alignment 分析代码/锁文件指纹；回放要求逐键完全一致。运行开始指纹会贯穿到 PedPy 计算结束，双指纹复核前不写正式产物。
- observed v5 绑定 canonical Parquet、canonical meta 的相对路径、大小和 SHA-256；计算结束前再次复核输入与分析代码均未变化。simulation v5 从已哈希 raw snapshot 精确重建 canonical、provenance、metrics、support 和 summary；有正式仿真时 comparison v5 由当前 observed、simulation 与可信 SceneConfig 确定性重建，没有正式仿真但 preflight 已通过时只能生成全部指标为 `unavailable` 的 fail-closed hold comparison；report v5 再由 comparison 确定性重建。任一 wrapper 版本或内容被改均失败。
- `platform_boarding` 内部几何仍为 bbox proxy；当前速度指标也只是非发布资格的代理。因此即使数值过线，报告仍必须是 `candidate_not_validated`，不能声称期望速度已标定。
- alignment 当前全量回归为 Ruff 通过、`181 passed`，其中包含新 Python 子进程执行 runner `--list-scenes` 的 clean-process smoke。该反例曾捕获共享 Metro 的循环导入，上游随后修复；alignment 没有用预加载顺序绕过。
- 当前仍没有可发布的 10 分钟 simulation v5，但 Round 23 已解开构模前源区阻断。`platform_boarding` 通过 10.0 m 场景参数把完整 67 点下车点阵横向移出 boarding holding area；SceneConfig、Metro 容量证书、preflight 与 runtime 共用同一偏移。共享净距仍为 0.396 m、runtime spacing 仍为 0.4 m，holding polygon/净距缓冲/门轴冲突均从 60/64/4 降为 0，Metro 编译 error 为 0。正式进程实际完成 600/600，随后才被需求守恒发布门拒绝：entry admitted/pending=361/56，exit admitted/pending=170/197。当前 source-preflight v2 已刷新并记录 `runtime_status=ready`；旧 simulation v2 仅保留为历史，不再进入当前 comparison/report 链。
- 历史运行先后暴露并修复两个可泛化的准入缺陷：第 327 步下车源区净距契约不一致，以及第 558 步入口 Passenger 构造前无原子准入/FIFO 背压。修复后 600/600 可稳定完成，但 exit admitted/pending=195/172；把 horizon 延到 840 仅变为 197/170。因此 840 只是一项诊断，正式基线仍为 600，不能靠延长时长或降需求来掩盖 PTI 死锁与列车交换调度失步。
- 剩余通用修复属于 Metro core：train-specific exchange manifest、上/下车共用的 PTI 控制器、下车优先或有依据的混合策略、共享通道预约，以及有界 deadlock/hold。几何解锁后 Step 5 仍因当前正式 simulation 未发布而失败；Step 6 已生成当前指纹的 `unavailable/hold` comparison，Step 7 已生成不授权改参的 hold report。implementation/release 均为 `hold`。
- 2026-08-04 20:56 CST 已在 Metro `c8a52a41…` / alignment `de4aa2b7…` 上重新生成 `platform_boarding_source_preflight.json` 与 `acceptance_latest.json`。完整 verifier 确认当前指纹、176 项测试与 Ruff；Step 5 明确记录 `current-fingerprint source geometry preflight completed`。Step 1–3、8 通过，Step 4 因 observed analysis 指纹过期失败，Step 5/6 失败，Step 7 pending，implementation/release 均为 `hold`。本次源区失败已由编译期错误码复现，不再需要启动仿真撞到运行期放置异常。
- 2026-08-04 22:53 CST 的 Round 23 正式运行在 Metro `7c6f1b7f…` / alignment `0e102c03…` 上通过 preflight 与 Metro 编译并完成 600/600；耗时 807.5 秒。几何卡点已关闭，新的最前置 blocker 是运行后 entry/alighting pending 守恒。完整证据见 `docs/reviews/round_23_geometry_unblocked_600_runtime.md`。
- 2026-08-04 23:36 CST 已按依赖顺序刷新 observed v5、source-preflight v2、comparison v5 与 parameter report v5。完整 verifier 记录 alignment `d86f1720…` / Metro `27b15d94…`，Step 4、7 通过，Step 5 只剩“当前正式 simulation 未发布”，Step 6 因 simulation unavailable、proxy 几何和速度代理资格不足保持科学 `hold`；验收中不再出现 stale/missing。
- 当前信任模型可防偶然损坏、串档和中途源码变化；raw trace 与 manifest 尚无外部签名/append-only evidence root，主动对抗性重标记属于明确 P2 边界。
- Step 5 正式阶梯基础设施已实现并经合成/故障注入测试：
  `alignment_ladder_manifest.v1` 严格 schema、注册的 final/nightly control profiles、固定
  entry-tail 断面/1.6 m 净宽/120--300 s 窗口、`1.2--1.5 persons/(m*s)` 双边门，以及只由
  final mixed control 切换 active simulation v5 的原子发布器。当前真实 Metro 机制修复尚未
  合流并跑完阶梯，因此状态是 `implemented/tested`，不是 `demonstrated`，Step 5 仍保持
  hold。
- 最新数值、正式 10 分钟运行规模和聚合状态以 `docs/acceptance_latest.json` 为唯一当前证据；旧 round 只保留为历史，不得引用为当前通过。
- 逐步证据入口：`uv run --project . python scripts/verify_acceptance.py --out docs/acceptance_latest.json`。

### 复核脚本（按轮次）

- 运行：
  - `uv run python scripts\\run_alignment_agent_checks.py --round 1`
  - 可多次调用，`--round 2`、`--round 3` 表示不同阶段复核
- 建议每轮把输出持久化：
  - `uv run python scripts\\run_alignment_agent_checks.py --round 2 --out docs/agent_audit_round_2.json`

#### 按视角拆分的独立 Agent（建议多轮触发）

- 代码/论文对齐 Agent：
  - `uv run python scripts\\agent_code_review.py --round 1 --out docs/agent_code_review_round_1.json`
- Metro 集成兼容 Agent：
  - `uv run python scripts\\agent_metro_compatibility.py --round 1 --out docs/agent_metro_compatibility_round_1.json`
- 通用性/反补丁 Agent：
  - `uv run python scripts\\agent_generality.py --round 1 --out docs/agent_generality_round_1.json`
- 三方聚合（任一 P0/P1 均非零退出）：
  - `uv run python scripts\\run_alignment_agent_checks.py --round 1 --out docs/agent_audit_round_1.json`

`run_alignment_agent_checks.py` 也支持按单视角运行：

- `uv run python scripts\\run_alignment_agent_checks.py --round 1 --agent paper_methodology`
- `uv run python scripts\\run_alignment_agent_checks.py --round 1 --agent metro_integration`
- `uv run python scripts\\run_alignment_agent_checks.py --round 1 --agent generality`

## 3. 边界与隔离（必读，违反会出事）

师兄目前每天改 70+ 个文件，热区是 `packages/`、`quality/`、`tests/`。两个人同时改会冲突。

### 3.1 隔离先例

仓库里已经有这个模式，照抄就行：

```
experiments/torch_movement_p0/    ← 有自己的 .venv
experiments/torch_movement_p1/    ← 有自己的 .venv
```

去看根目录 `pyproject.toml`，你会发现这两个：

- **不在** `[tool.uv.workspace].members` 列表里
- **不在** `[tool.importlinter].root_packages` 列表里

意思是：它们装什么依赖、代码怎么组织，主线完全不管。我们的 `alignment/` 用同一套待遇。

### 3.2 铁律

| # | 规则 | 违反后果 |
|---|---|---|
| 1 | 只写 `alignment/`，其他目录**一律只读** | 跟师兄冲突 |
| 2 | **不改**根 `pyproject.toml` | 拉崩主线依赖 |
| 3 | 原始数据**不进 git** | 仓库膨胀到几十 GB |
| 4 | 每个数据集必须记 license 和 citation | 学术问题 |
| 5 | 仿真侧只读 `movement_trace` | 分析了伪造数据 |
| 6 | commit message 加 `[alignment]` 前缀 | 师兄没法过滤 |

---

## 4. 目录结构

```
alignment/
├── README.md                       ← 本文件
├── pyproject.toml                  ← 独立包声明
├── .gitignore                      ← 第一天就要写好
├── src/
│   └── metro_alignment/
│       ├── __init__.py
│       ├── datasets/
│       │   ├── __init__.py
│       │   ├── registry.py         ← 数据集元信息（URL/md5/license/引用）
│       │   ├── download.py         ← 下载 + 校验 + 续传
│       │   ├── eindhoven.py        ← 各数据集 loader
│       │   ├── julich.py
│       │   └── atc.py
│       ├── canonical.py            ← 统一轨迹格式（本项目的地基）
│       ├── metrics/
│       │   ├── __init__.py
│       │   ├── fundamental.py      ← 基本图、速度、密度、流量（包 PedPy）
│       │   └── comparison.py       ← 观测 vs 仿真
│       ├── scenes/
│       │   ├── __init__.py
│       │   ├── corridor_unidirectional.py
│       │   ├── bottleneck.py
│       │   └── platform_boarding.py
│       └── report.py               ← 生成对照报告
├── scripts/
│   ├── download_all.py
│   ├── build_canonical.py
│   ├── compute_observed_metrics.py
│   ├── run_alignment_scene.py
│   └── compare_with_simulation.py
├── data/
│   ├── raw/                        ← 原始下载，不进 git（约 15–20 GB）
│   ├── canonical/                  ← 统一格式 parquet，不进 git
│   └── metrics/                    ← JSON 小文件，**进 git**（这是交付物）
├── notebooks/                      ← 探索用，不进 git
├── docs/
│   └── DATASETS.md                 ← 数据集详细说明和引用
└── tests/
    ├── test_canonical.py
    └── test_registry.py
```

### 4.1 `.gitignore`（**第一天就写，否则会把 5 GB 提交上去**）

```gitignore
data/raw/
data/canonical/
notebooks/
.venv/
__pycache__/
*.pyc
*.parquet
*.csv
*.txt.gz
!data/metrics/*.json
!docs/**
```

注意 `!data/metrics/*.json` 那行：指标 JSON 是小文件，**要**进 git。

### 4.2 `pyproject.toml`

```toml
[project]
name = "metro-alignment"
version = "0.1.0"
description = "Open pedestrian dataset alignment and parameter calibration for metro station simulation"
requires-python = ">=3.12"
dependencies = [
    "pedpy>=1.4.0",
    "pandas>=2.0",
    "pyarrow>=15.0",
    "numpy>=1.26",
    "shapely>=2.0",
    "matplotlib>=3.8",
    "requests>=2.31",
    "tqdm>=4.66",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/metro_alignment"]
```

**再说一遍：不要动根目录的 `pyproject.toml`。**

---

## 5. 环境搭建

```bash
cd D:\metro\alignment
uv venv
.venv\Scripts\activate
uv pip install -e ".[dev]"
python -c "import pedpy; print(pedpy.__version__)"
```

看到版本号（应该 ≥1.4.0）就成了。

### 5.1 先跑通 PedPy 官方示例（不要跳过）

在写任何自己的代码之前，先把 PedPy 官方的两个 notebook 跑通：

1. **Getting Started** —— 了解 `load_trajectory` 和基本数据结构
2. **Fundamental Diagram** —— 这是我们最核心的产出

文档：https://pedpy.readthedocs.io/stable/

**为什么必须先跑官方示例**：PedPy 的核心概念是 `WalkableArea`（可行走区域）、`MeasurementArea`（测量区域）、`MeasurementLine`（测量断面）。这三个概念不理解，后面所有指标都算不对。官方 notebook 用他们自带的样例数据讲这三个概念，半天能懂。

**为什么不自己写算法**：密度的定义方式有好几种（经典密度、Voronoi 密度、高斯核密度），速度的定义也有好几种（瞬时、位移、Voronoi 加权）。审稿人认 PedPy 的实现，不认你手搓的。手搓还容易在边界处理上出错。

### 5.2 常用 PedPy API 速查

以官方文档为准（版本会变），大致是：

```python
import pedpy
from pedpy import (
    load_trajectory,
    WalkableArea,
    MeasurementArea,
    MeasurementLine,
    compute_individual_speed,
    compute_mean_speed_per_frame,
    compute_classic_density,
    compute_voronoi_density,
    compute_flow,
    compute_n_t,
    SpeedMethod,
)
```

---

## 6. 数据集清单

### 冻结 holdout 与多种子 nightly

Eindhoven calibration/holdout 的冻结合同和输入 SHA 由以下命令生成；它会全量扫描时间与 agent ID，发现不独立时 fail closed：

```powershell
uv run --project . python scripts/freeze_calibration_holdout_split.py
```

新 mixed-600 bundle 到达后，把 seeds 41–50 的 `alignment_simulation_metrics.v5` manifest 放在同一根目录下（可分子目录），再执行：

```powershell
uv run --project . python scripts/aggregate_multi_seed.py `
  --input-dir <new-bundle-root> `
  --out data/metrics/multi_seed_platform_boarding.json
```

聚合器验证固定 seed 集、逐种子 Step-5 最终计数和共同 cohort 指纹，并计算 Student-t 95% CI；相对半宽不超过 5% 才收敛。`--legacy-smoke` 只用于旧数据管道 smoke，输出永远不具备 release 资格。

### 6.1 总览

| 优先级 | 数据集 | 场景 | 大小 | License | 能标定什么 |
|---|---|---|---|---|---|
| P0 | Eindhoven 站台 | 火车站站台 | 4.6 GB | CC-BY-4.0 | 站台等候分布、上下客 |
| P0 | Jülich 数据档案 | 受控实验 | 按需 | 署名即可 | 自由流速度、基本图、瓶颈通行能力 |
| P1 | 楼梯扶梯数据集 | 车站垂直设施 | 待确认 | 待确认 | **楼梯/扶梯四个参数（价值最高）** |
| P2 | ATC 大阪 | 大型室内 | 很大 | 研究用 | 自由行走、多向流 |
| P2 | Utrecht / Amsterdam Zuid | 火车站站台 | 待确认 | 待确认 | 站台容量 |

### 6.2 P0-A：Eindhoven Centraal 站台

- **DOI**：`10.5281/zenodo.13784588`
- **页面**：https://zenodo.org/records/13784588
- **License**：CC-BY-4.0（可自由使用，必须署名）
- **论文**：arXiv:2407.20794 —— *Data-driven physics-based modeling of pedestrian dynamics*
- **配套代码**：https://github.com/c-pouw/physics-based-pedestrian-modeling

**内容**：Eindhoven 中央站 2 号站台（通往 3/4 号轨道），60 个连续日，10 fps。为隐私已移除真实日期时间。附一张站台俯视图。

**字段**（只有 4 个）：

| 字段 | 单位 | 说明 |
|---|---|---|
| `time_ms` | 毫秒 | 从测量开始的经过时间 |
| `object_identifier` | — | 个体唯一 id |
| `x_position_mm` | 毫米 | x 坐标 |
| `y_position_mm` | 毫米 | y 坐标 |

**文件清单**（共 4.6 GB，**先只下第一个**）：

| 文件 | 大小 | md5 |
|---|---|---|
| `Eindhoven_centraal_platform_3_4.png` | 467 kB | `6978659b7af6e0f813e43f5aef2c2e51` |
| `Eindhoven_centraal_trajectories_days_01_10.parquet` | 862.1 MB | `34f1b0c41d93184f0ae30a45246f82dc` |
| `..._days_11_20.parquet` | 643.2 MB | `48dfb09889cca222252ad9fb47913b0e` |
| `..._days_21_30.parquet` | 714.3 MB | `1b6cdb6d80b9f6348e66eabbb7b25d11` |
| `..._days_31_40.parquet` | 679.9 MB | `b42654e6d45c0e3fca1fe58b264a71fc` |
| `..._days_41_50.parquet` | 938.7 MB | `c12420a5d735ea1cb5db52320815b9cd` |
| `..._days_51_60.parquet` | 757.1 MB | `f3381718f3954baa54e102f6cb5cef01` |

下载 URL 格式：

```
https://zenodo.org/records/13784588/files/<文件名>?download=1
```

**引用**（写进 `registry.py`）：

```
Pouw, C.A.S., van der Vleuten, G.G.M., Corbetta, A., & Toschi, F. (2024).
Data-driven physics-based modeling of pedestrian dynamics - dataset:
Pedestrian trajectories at Eindhoven train station.
Zenodo. https://doi.org/10.5281/zenodo.13784588
```

**注意**：这是**站台**数据，不是楼梯扶梯数据。别指望它给楼梯分流比。

### 6.3 P0-B：Jülich 行人动力学数据档案

- **入口**：https://ped.fz-juelich.de/database
- **DOI**：`10.34735/ped.da`
- **机构**：Forschungszentrum Jülich, IAS-7 (Civil Safety Research)
- **使用条件**：可自由用于研究，必须注明数据来源

**这个不能脚本批量下载**，是个 wiki 式档案，要人工进去挑实验条目，每个条目有自己的下载链接和元数据（几何尺寸、参与人数、密度）。

**要挑的四类实验**：

| 实验类型 | 挑几组 | 用来标定 |
|---|---|---|
| 单向直走廊 unidirectional corridor | 3–5 组不同密度 | `jupedsim_desired_speed_mps`、基本图 |
| 瓶颈 bottleneck | 3–5 组不同宽度 | 闸机通行能力、`gate_service_persons_per_min` |
| T 型交叉 T-junction | 2–3 组 | 汇流行为 |
| 弯走廊 rounded corridor | 2–3 组 | 转弯减速 |

**挑选时必须记下的元数据**（后面建对照场景要用）：

- 走廊/瓶颈的**几何尺寸**（宽、长）
- **参与人数**
- **入口流率**或初始密度
- 帧率
- 坐标单位（Jülich 一般是**米**）

**好消息**：PedPy 原生支持 Jülich 的轨迹格式，`load_trajectory` 直接能读。

### 6.4 P1：楼梯扶梯数据集（第一天就去查）

- **论文**：arXiv:2307.15609 —— *High-statistics pedestrian dynamics on stairways and their probabilistic fundamental diagrams*
- **期刊版**：Transportation Research Part C（ScienceDirect S0968090X23004588）

**内容**（据论文摘要）：Eindhoven 中央站一个楼梯+扶梯组合，2021.4–2022.5 连续一年，每天 6:00–22:00，四个头顶深度传感器，约 **300 万条轨迹**。

**这份如果拿得到，是全场价值最高的**。它直接给：

| 参数 | 当前默认值 |
|---|---|
| `stairs_preference_share` | 0.18 |
| `stair_fatigue_cost_up` / `_down` | 0.6 / 0.15 |
| `stair_bidirectional_conflict_factor` | 0.3 |
| `stairs_speed_units_per_tick` | 1.55 |

而且论文给的是**概率型基本图**——不是一条曲线而是一个分布带，可以判仿真落没落在带内，比对单一均值严格得多。

**第一天的任务**：读论文的 *Data availability* 声明，确认数据是否公开、在哪个仓库、什么 license。找到了立刻更新本文档。

### 6.5 P2：ATC 大阪购物中心

- **入口**：https://dil.atr.jp/crest2010_HRI/ATC_dataset/
- **内容**：Asia & Pacific Trade Center（大阪），49 个 3D 传感器，约 900 m²，92 天，每天 9:00–21:00
- **格式**：CSV，一天一个文件；另附 ROS 格式 2D 占用栅格地图（**同坐标系**，几何对齐很省事）
- **使用条件**：仅限研究用途，必须引用

**引用**：

```
D. Brščić, T. Kanda, T. Ikeda, T. Miyashita.
"Person position and body direction tracking in large public spaces using 3D range sensors."
IEEE Transactions on Human-Machine Systems, Vol. 43, No. 6, pp. 522-534, 2013.
```

**先只下 1 天试试**，总量很大。

### 6.6 P2：荷兰铁路站台（待确认）

- Utrecht Centraal（track 5）：4TU.ResearchData
- Amsterdam Zuid（track 1-2）：TU Delft Research Portal
- 来源：博士论文 *Mind your passenger! The passenger capacity of platforms at railway stations in the Netherlands*

**待确认**：是否需要注册账号、license 条款。

### 6.7 磁盘预算

| 数据集 | 预估 |
|---|---|
| Eindhoven 站台 | 4.6 GB |
| Jülich（挑 15 组） | 约 1–2 GB |
| 楼梯扶梯 | 待确认，可能 >5 GB |
| ATC（1 天） | 约 1 GB |
| canonical 转换后 | 约等于原始的 60% |
| **合计** | **15–20 GB** |

**动手前先确认 D 盘空间。**

---

## 7. 下载实现要点

`src/metro_alignment/datasets/download.py` 必须做到三件事，缺一个你都会在网络断掉的时候崩溃：

### 7.1 断点续传

用 HTTP `Range` 头。已下载 `n` 字节就从 `n` 开始续：

```python
headers = {}
if partial_path.exists():
    headers["Range"] = f"bytes={partial_path.stat().st_size}-"
resp = requests.get(url, headers=headers, stream=True, timeout=60)
# 服务器返回 206 = 支持续传；返回 200 = 不支持，要从头下
```

先下到 `<文件名>.partial`，校验通过后再改名成正式文件。这样中断的半截文件不会被误当成完整文件。

### 7.2 md5 校验

下完立刻校验。**不对就删掉重下，不要留着**：

```python
def verify_md5(path: Path, expected: str) -> bool:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == expected
```

### 7.3 幂等

已存在且校验通过的文件直接跳过。这样 `download_all.py` 可以随时重跑，不会重复下载。

### 7.4 数据集注册表

`src/metro_alignment/datasets/registry.py`：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FileSpec:
    name: str
    url: str
    md5: str
    size_bytes: int


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str  # "eindhoven_platform_v1"
    title: str
    source_url: str
    license: str  # "CC-BY-4.0"
    citation: str  # 完整引用，论文里要用
    files: tuple[FileSpec, ...]
    coordinate_unit: str  # "mm" | "m"
    frame_rate_hz: float
    notes: str

    def __post_init__(self) -> None:
        if not self.license.strip():
            raise ValueError(f"{self.dataset_id}: license 不能为空")
        if not self.citation.strip():
            raise ValueError(f"{self.dataset_id}: citation 不能为空")
        if self.coordinate_unit not in {"mm", "m"}:
            raise ValueError(f"{self.dataset_id}: 不支持的坐标单位")
```

`__post_init__` 里那两个非空检查是**故意的**——强制你在加数据集的时候就把出处填好，而不是等到写论文时回头找。

---

## 8. Canonical 格式（本项目的地基）

四个数据集格式全不一样：Eindhoven 是毫米+毫秒 parquet，Jülich 是米+帧号 txt，ATC 是毫米 CSV。**必须先统一**，否则后面每个分析都要写四遍。

### 8.1 格式定义

`src/metro_alignment/canonical.py`：

```python
CANONICAL_SCHEMA_VERSION = "alignment_trajectory.v1"

CANONICAL_COLUMNS = {
    "dataset_id": "string",  # 数据集标识
    "agent_id": "int64",  # 个体唯一 id（跨数据集不重复）
    "frame": "int64",  # 帧号，从 0 开始
    "t_s": "float64",  # 秒，从 0 开始
    "x_m": "float64",  # 米
    "y_m": "float64",  # 米
}
```

**列名固定，单位固定，不许改。** 后面所有分析代码都依赖它。

### 8.2 转换规则

1. 长度一律转成**米**：Eindhoven `x_position_mm / 1000`，ATC 同理，Jülich 已经是米则不变
2. 时间一律转成**秒**：Eindhoven `time_ms / 1000`
3. 时间**平移到从 0 开始**：`t_s = t_s - t_s.min()`
4. `agent_id` 加数据集偏移，防止跨数据集撞号：

```python
DATASET_ID_OFFSET = {
    "eindhoven_platform_v1": 10_000_000,
    "julich_corridor": 20_000_000,
    "atc_osaka": 30_000_000,
}
```

5. 按 `(agent_id, t_s)` 排序
6. 输出 `data/canonical/{dataset_id}.parquet`

### 8.3 附带元数据

每个 canonical 文件旁边放一个 `{dataset_id}.meta.json`：

```json
{
  "schema_version": "alignment_trajectory.v1",
  "dataset_id": "eindhoven_platform_v1",
  "source_url": "https://zenodo.org/records/13784588",
  "license": "CC-BY-4.0",
  "citation": "Pouw, C.A.S., et al. (2024). ...",
  "row_count": 123456789,
  "agent_count": 987654,
  "duration_s": 5184000.0,
  "frame_rate_hz": 10.0,
  "x_range_m": [0.0, 42.5],
  "y_range_m": [0.0, 9.8],
  "speed_p50_m_s": 1.18,
  "speed_p99_m_s": 2.41,
  "built_at": "2026-08-05T14:22:00+08:00"
}
```

### 8.4 验收测试（`tests/test_canonical.py`）

每个数据集转换后必须全部通过：

| # | 检查 | 失败意味着 |
|---|---|---|
| 1 | 列名和 dtype 完全符合 schema | 转换代码写错 |
| 2 | `t_s` 在每个 `agent_id` 内**严格单调递增** | 排序或去重有问题 |
| 3 | 没有 NaN / inf | 源数据有脏值，要处理 |
| 4 | 坐标范围 < 1000 m | **单位换算错了** |
| 5 | **速度 p99 < 3 m/s** | **单位换算错了** |
| 6 | `agent_id` 跨数据集不重复 | 偏移量没加或撞了 |
| 7 | `meta.json` 的 `license` / `citation` 非空 | 注册表没填 |

> **第 4、5 条最重要。** 单位搞错是这类工作最常见的 bug——毫米当成米，速度会大 1000 倍；忘了除以 1000，坐标会到几万。不做这两个检查，你会一路错到出图才发现。

---

## 9. 观测侧指标

`scripts/compute_observed_metrics.py`，对每个 canonical 数据集算下面这些，用 PedPy，**不要手搓**。

### 9.1 指标清单

| 指标 | PedPy 大致函数 | 对应我们哪个参数 |
|---|---|---|
| 低全局密度步行速度代理 | `compute_individual_speed` | 仅作 `jupedsim_desired_speed_mps` 的候选诊断，当前不具发布资格 |
| 基本图（密度-速度） | `compute_classic_density` / `compute_voronoi_density` + 速度 | 整体运动模型 |
| 断面流量 | `compute_flow` / `compute_n_t` | 通行能力 |
| 密度剖面 | `compute_density_profile` | 拥挤空间分布 |

### 9.2 当前步行速度代理怎么取

当前薄切片采用可重放但较弱的经典密度口径：在同一显式 `MeasurementArea` 内，保留
`density <= 0.3 persons/m²` 且 `0.5 <= speed <= 3.0 m/s` 的个体速度。它筛的是测量区的
**全局平均密度**，没有证明每个行人在局部空间中不受他人影响；速度下限还会截断慢行样本。
所以产物键名是 `low_global_density_walking_speed_proxy_m_s`，并明确
`desired_speed_release_eligible=false`。阈值、区域、PedPy 版本和速度算法全部写入 artifact。
若要声称自由流/期望速度标定，必须另行实现局部隔离判据（例如局部邻域或 Voronoi）并独立验证。

### 9.3 密度用哪种

- **经典密度**（`compute_classic_density`）：测量区域内人数 / 区域面积。简单，但对区域边界敏感
- **Voronoi 密度**（`compute_voronoi_density`）：每个人分配一块 Voronoi 多边形，密度 = 1/面积。**更稳健，是现在的主流做法**

**先用经典密度跑通流程，再上 Voronoi。** Voronoi 需要正确定义 `WalkableArea`，一开始容易配错。

### 9.4 输出格式

`data/metrics/{dataset_id}_observed.json`，**这些是小文件，要进 git**，是你的交付物：

```json
{
  "dataset_id": "julich_corridor_uni_d1.5",
  "pedpy_version": "1.4.0",
  "measurement_area_wkt": "POLYGON ((...))",
  "metrics": {
    "low_global_density_walking_speed_proxy_m_s": {
      "n": 8421,
      "p5": 0.89, "p25": 1.12, "p50": 1.34, "p75": 1.51, "p95": 1.78,
      "mean": 1.33, "std": 0.27
    },
    "fundamental_diagram": {
      "method": "voronoi",
      "bins": [
        {"density_p_m2": 0.5, "speed_p50": 1.31, "speed_p5": 1.02, "speed_p95": 1.62, "n": 1204}
      ]
    }
  }
}
```

每个指标必须带 **样本量 `n`** 和 **分位数**，不要只给均值。均值掩盖分布形状，而我们后面要判「仿真有没有落在观测的带内」，需要分位数。

---

## 10. 融入仿真对照

到这一步才碰仿真，但**仍然只读**。

### 10.1 思路

把观测的场景在仿真里复现一遍，用**同一套 PedPy 代码**算指标，然后比。

### 10.2 建对照微场景

仓库里有现成模式可以抄：`quality/metro_station_testkit/src/metro_station_testkit/goal_*_micro_scene.py`。

**你在 `alignment/src/metro_alignment/scenes/` 下写自己的版本，不要改 testkit。**

三个场景：

| 场景文件 | 对照哪个观测 | 几何要求 |
|---|---|---|
| `corridor_unidirectional.py` | Jülich 直走廊 | 宽、长、人数、入口流率跟实验一致 |
| `bottleneck.py` | Jülich 瓶颈 | 瓶颈宽度、上游区域尺寸一致 |
| `platform_boarding.py` | Eindhoven 站台 | 站台尺寸、列车门位置一致 |

**几何一致是硬要求。** Jülich 实验的尺寸在条目元数据里都有，照着建。几何不一致，比出来的差异没有意义。

### 10.3 跑仿真取轨迹

```python
# 1) 确认时钟是 physical，否则拿到空 trace
scenario = replace(scenario, simulation_clock_mode="physical")

# 2) 跑完后取权威轨迹
trace = model.movement_backend.movement_trace()
points = trace["points"]  # [{passenger_id, time_seconds, x, y, level_id, episode_id, ...}]
```

**三个坑**：

1. **必须是 `physical` 时钟**。如果是默认的 `legacy_scaled`，`_movement_trace_recorder_for` 会返回 `None`，`movement_trace()` 给你一个 `enabled: false, reason: "non_physical_simulation_clock"` 的空壳。
2. **只用 `movement_trace`，不用 `visual_tracks`**。后者约 19% 的点是表现层插值伪造的，`meta.visual_only == true`。
3. 采样间隔由 `movement_trace_sample_seconds` 控制，默认 0.2 秒。跟 PedPy 分析的时间分辨率要匹配。

### 10.4 转 canonical

把 `movement_trace` 的点转成第 8 节的 canonical 格式：

| movement_trace | canonical |
|---|---|
| `(passenger_id, episode_id)` | `agent_id`（episode identity 映射到仿真命名空间 `>=90_000_000`） |
| `time_seconds` | `t_s` |
| `x` | `x_m` |
| `y` | `y_m` |

**仿真坐标已经是米**，不用换算。但还是要跑第 8.4 节那七条验收测试。

这样观测和仿真走完全同一套分析代码——**这是整个设计的核心**。

### 10.5 出对照

`scripts/compare_with_simulation.py` → `data/metrics/comparison_{scene}.json`：

```json
{
  "scene_id": "corridor_unidirectional_d1.5",
  "observed_dataset_id": "julich_corridor_uni_d1.5",
  "overall_verdict": "hold",
  "metrics": {
    "low_global_density_walking_speed_proxy_m_s": {
      "observed": 1.34, "simulated": 1.21, "rel_error": -0.097,
      "verdict": "within_band",
      "support": {"observed": {"agent_n": 890, "window_n": 5}, "simulated": {"seed_n": 1}}
    },
    "fundamental_support_coverage": {"simulated": 0.91, "verdict": "within_band"},
    "fundamental_conditional_in_band_fraction": {"simulated": 0.83, "verdict": "within_band"}
  }
}
```

### 10.6 判据（先松后紧）

**第一轮只要求**：

| 指标 | 阈值 |
|---|---|
| 低全局密度步行速度代理中位数相对误差 | ≤ 15% |
| 基本图观测支持覆盖率 | ≥ 80%，至少 3 个双方 `n>=30` 的箱，并覆盖到 `>0.3 人/m²` |
| 有观测支持部分的 p5–p95 条件带内占比 | ≥ 80% |

**别一上来定 5%。** 第一轮肯定过不了，会打击信心，也会诱使你去调参凑数。先拿到数字，再和师兄一起定正式阈值。

---

## 11. 交付物

每周三样：

### 11.1 数据集清单表（更新到 `docs/DATASETS.md`）

| dataset_id | 来源 | License | 引用 | 大小 | 状态 |
|---|---|---|---|---|---|
| `eindhoven_platform_v1` | Zenodo 13784588 | CC-BY-4.0 | Pouw et al. 2024 | 4.6 GB | ✅ 已下载 |

### 11.2 指标 JSON（`data/metrics/*.json`，进 git）

### 11.3 参数对照表（最终交付给师兄）

| 参数 | 当前值 | 观测值 | 样本量 | 来源 | 建议 |
|---|---|---|---|---|---|
| `jupedsim_desired_speed_mps` | 1.2 | 1.34 (p50) | n=8421 | Jülich 直走廊 | 上调至 1.34 |
| `stairs_preference_share` | 0.18 | — | — | 待楼梯数据集 | 阻塞 |

**这张表是整个工作的最终产物。**

---

## 12. 时间表

| 天 | 任务 | 完成标志 |
|---|---|---|
| 1 | 第 3–5 节：建目录、装环境、跑通 PedPy 官方 notebook；查楼梯数据集可得性 | `pedpy.__version__` 打得出来；官方基本图 notebook 出图 |
| 2–3 | 写 `registry.py` + `download.py`；下 Eindhoven 第一个文件 | md5 校验通过；断网重连能续传 |
| 4–5 | 第 8 节 canonical 格式 + 七条验收测试 | `pytest alignment/tests` 全绿 |
| 6–7 | 挑 Jülich 走廊和瓶颈实验，下载，转 canonical | 至少 6 组实验进 canonical |
| 8–10 | 第 9 节观测指标 | 每个数据集有 `_observed.json` |
| 11–14 | 第 10 节对照场景 + 首轮对照 | 至少 1 个场景出 `comparison_*.json` |

两周出第一版参数对照表。

> **第 4–5 天那步做扎实**。canonical 格式是地基，它错了后面全错，而且发现得很晚。

---

## 13. 常见坑

| 症状 | 原因 | 怎么查 |
|---|---|---|
| 速度算出来 1000+ m/s | 毫米没转米 | 看 `meta.json` 的 `speed_p99_m_s` |
| 坐标范围到几万 | 同上 | 看 `x_range_m` |
| 速度全是 0 | 时间单位错了（毫秒当秒） | 看 `t_s` 的 diff 中位数，应该 ≈ 1/帧率 |
| `movement_trace` 是空的 | 时钟不是 `physical` | 看返回的 `metadata.reason` |
| 基本图形状怪异 | `MeasurementArea` 配错，或包含了边界效应 | 画出来看，把测量区域缩到走廊中段 |
| 两个数据集的 agent 混了 | `agent_id` 偏移没加 | 测试第 6 条 |
| git 提交巨慢 | 数据进 git 了 | `git status` 看有没有 parquet |
| 想把当前速度代理写成自由流 | 尚未做局部隔离判据，且存在速度截断 | 见 9.2；保持 scientific hold |

---

## 14. 引用与许可

论文里必须署名的：

**Eindhoven 站台**
```
Pouw, C.A.S., van der Vleuten, G.G.M., Corbetta, A., & Toschi, F. (2024).
Data-driven physics-based modeling of pedestrian dynamics - dataset:
Pedestrian trajectories at Eindhoven train station.
Zenodo. https://doi.org/10.5281/zenodo.13784588   [CC-BY-4.0]
```

**Jülich 数据档案**
```
Pedestrian Dynamics Data Archive, Forschungszentrum Jülich, IAS-7.
https://doi.org/10.34735/ped.da
（各实验条目另有自己的引用要求，逐条记录）
```

**ATC 大阪**
```
D. Brščić, T. Kanda, T. Ikeda, T. Miyashita (2013).
"Person position and body direction tracking in large public spaces using 3D range sensors."
IEEE Transactions on Human-Machine Systems, 43(6), 522-534.
```

**PedPy**
```
PedPy — Pedestrian Trajectory Analyzer.
Forschungszentrum Jülich GmbH, IAS-7. MIT License.
https://github.com/PedestrianDynamics/pedpy
```

---

## 15. 相关链接

| 资源 | 链接 |
|---|---|
| PedPy 文档 | https://pedpy.readthedocs.io/stable/ |
| PedPy 源码 | https://github.com/PedestrianDynamics/pedpy |
| Jülich 数据档案 | https://ped.fz-juelich.de/database |
| Eindhoven 数据集 | https://zenodo.org/records/13784588 |
| Eindhoven 配套代码 | https://github.com/c-pouw/physics-based-pedestrian-modeling |
| ATC 数据集 | https://dil.atr.jp/crest2010_HRI/ATC_dataset/ |
| 楼梯基本图论文 | https://arxiv.org/abs/2307.15609 |
| AFC 反推站内走行时间（方法参考） | https://doi.org/10.3390/su15086660 |

---

## 附录 A：第一天检查清单

- [ ] 读完本文档第 0–3 节
- [ ] 确认 D 盘剩余空间 > 25 GB
- [ ] 建好目录骨架（第 4 节）
- [ ] **`.gitignore` 写好并验证**（`git status` 看不到 `data/raw/`）
- [ ] `uv venv` + `uv pip install -e ".[dev]"` 成功
- [ ] `python -c "import pedpy; print(pedpy.__version__)"` 有输出
- [ ] PedPy 官方 Getting Started notebook 跑通
- [ ] PedPy 官方 Fundamental Diagram notebook 跑通并出图
- [ ] 读 arXiv 2307.15609 的 Data availability，确认楼梯数据集能否拿到
- [ ] 确认自己**没有**修改 `alignment/` 以外的任何文件（`git status` 检查）

## 附录 B：求助前先自查

1. 报错信息完整读一遍（不是只看最后一行）
2. 对照第 13 节常见坑
3. 确认 PedPy 官方 notebook 还能跑（排除环境问题）
4. 把「我做了什么 / 期望什么 / 实际什么 / 完整报错」写清楚再问

## 附录 C：验收执行入口（按轮次）

- Step 明细与每步可量化指标请见：[acceptance_criteria_by_step.md](/D:/metro/alignment/docs/acceptance_criteria_by_step.md)
- 三类审查 Agent（多轮）入口：
  - 全量：`uv run python scripts/run_alignment_agent_checks.py --round <N> --out docs/agent_audit_round_<N>.json`
  - 业界/论文视角：`uv run python scripts/agent_code_review.py --round <N> --out docs/agent_code_review_round_<N>.json`
  - Metro 协作视角：`uv run python scripts/agent_metro_compatibility.py --round <N> --out docs/agent_metro_compatibility_round_<N>.json`
  - 通用性视角：`uv run python scripts/agent_generality.py --round <N> --out docs/agent_generality_round_<N>.json`
