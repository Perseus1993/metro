# Alignment 计划执行清单（验收驱动）

目标：实现“开放行人数据 → canonical 统一轨迹 → PedPy 观测指标 → 仿真对照 → 参数建议”闭环；软件实现门与科学标定门分开判定，阈值未过时必须明确 `hold`。

当前执行边界（2026-08-04）：Eindhoven + platform proxy 为 Now 薄切片；Jülich corridor、bottleneck 和 ATC 数据仍为 `pending`，不能计入完成度。逐步量化门以 `docs/acceptance_criteria_by_step.md` 和 `scripts/verify_acceptance.py` 为准。

当前状态（2026-08-04 23:36 CST）：Round 23 已把 `platform_boarding` 下车源点阵横向错开 10.0 m，并让 SceneConfig、Metro 编译容量证书、preflight 与 runtime 共用该参数。正式配置保持 10 分钟、1 秒/tick、`horizon_steps=demand_steps=600`、入口/出口 2500/2200 人/小时。当前 preflight 为 67/67 唯一候选，holding polygon/净距缓冲/门轴冲突均为 0，Metro 编译 error 为 0；正式进程实际完成 600/600，卡点 1 已从 `runtime_status=not_started` 解锁。运行结束后的发布守恒门仍 fail：entry admitted/pending=361/56，exit admitted/pending=170/197，所以没有发布新 simulation v5。证据链已刷新到 alignment `d86f1720…` / Metro `27b15d94…`：Step 4 pass，Step 5 仅因当前正式 simulation 未发布而 fail，Step 6 为当前 `unavailable/hold`，Step 7 pass 且不授权改参；release 继续 `hold`。详见 `docs/reviews/round_23_geometry_unblocked_600_runtime.md` 与 `docs/acceptance_latest.json`。

## 全局验收规则（每步都需要）
- 对齐专属逻辑只改 `alignment/`；若编译证书与 runtime 必须共用同一几何参数，可最小修改 `packages/metro_station/` 的场景/几何契约，并必须补根仓库回归。Round 23 的 lateral offset 与网格精度修复属于该例外。
- 不改仓库根 `pyproject.toml`。
- `alignment/.gitignore` 生效，`data/raw`、`data/canonical`、`notebooks` 不入 git。
- 输出交付文件仅限 `data/metrics/*.json` 与 `docs/*`（本步默认允许）。
- 所有脚本可在 `alignment` 虚拟环境中重入执行，支持中断重试。

## Step 1：基础工程化
- 产出文件：`alignment/pyproject.toml`、`alignment/.gitignore`、`alignment/src`、`alignment/scripts`、`alignment/docs`、`alignment/tests` 目录。
- 验收指标：
  - `uv venv && uv pip install -e ".[dev]"` 成功。
  - `python -c "import pedpy"` 可成功导入。

## Step 2：数据集注册与下载
- 产出文件：`src/metro_alignment/datasets/registry.py`、`src/metro_alignment/datasets/download.py`、`scripts/download_all.py`。
- 验收指标：
  - `python -m metro_alignment.datasets.registry` 打印注册表，且每条 `DatasetSpec` 都有非空 `license` 与 `citation`。
  - `download.py` 对 `Range` 不支持和支持两种返回都能正确处理。
  - 已校验成功的文件再次执行应直接跳过（幂等）。

## Step 3：Canonical 统一格式
- 产出文件：`src/metro_alignment/canonical.py`、`scripts/build_canonical.py`、`tests/test_canonical.py`。
- 验收指标：
  - 输出列/类型严格为 `CANONICAL_COLUMNS` 与 `CANONICAL_SCHEMA_VERSION`。
  - `t_s` 每个 `agent_id` 内严格递增且无 NaN/inf。
  - `|x_m|/|y_m|` 有界（绝大部分在 ±1000m 内）。
  - 自动生成 `*.meta.json`，`license` 与 `citation` 不空。

## Step 4：指标计算（观测侧）
- 产出文件：`src/metro_alignment/metrics/fundamental.py`、`scripts/compute_observed_metrics.py`。
- 验收指标：
  - 每个入库的 canonical 文件可导出 `data/metrics/{dataset_id}_observed.json`。
  - JSON 字段包含 `metrics.low_global_density_walking_speed_proxy_m_s` 分位数（至少 p5/p25/p50/p75/p95）和 `n`；明确它不是局部隔离自由流或期望速度。
  - 观测与仿真记录并强制匹配同一 `0.4s` 物理速度窗口、PedPy 版本、密度算法、分箱和共享测量多边形 hash。
  - analysis contract 必须能由实际 method/config/polygon 字段逐项反推一致；每个指标记录真实贡献 point/agent/frame/window/source-row，而非整份输入的泛化总数。
  - observed manifest 绑定 canonical 与 meta 的 path/size/SHA-256，并在计算前后验证输入和 analysis runtime 指纹均未改变。
  - `speed_p99_m_s` 在同场景下符合量级（<= 3.0 m/s）。

## Step 5：仿真轨迹可对齐
- 产出文件：`src/metro_alignment/scenes/*.py`、`scripts/run_alignment_scene.py`。
- 验收指标：
  - 对齐场景配置可独立生成，不改主线场景文件。
  - 仿真输出需产生真实的 `*_simulated.json`、`*.movement_trace.json` 与 canonical/metrics 落盘产物，`movement_trace` 不为空。
  - raw 身份和物理字段严格保持 JSON 类型；trace 采样间隔必须精确绑定可信 SceneConfig，raw trace 必须能重建 canonical、provenance、metrics、support 与 trajectory summary。
  - 仿真开始时捕获 Metro 与 alignment analysis 指纹，直到轨迹转换和 PedPy 指标计算完成后再次相等才允许写正式文件。
  - 每个仿真指标记录真实贡献 point/episode/passenger/frame/seed；episode canonical ID 对同一身份跨子集/全量稳定且碰撞硬失败。
  - 在 `build_model` 前按场景共享 `radius * clearance_multiplier`、真实峰值同 tick 下车批次和完整候选搜索窗口检查下车源区与上车 holding area/门轴通道；存在交叠时写当前指纹的结构化 blocker，runtime 不得启动，旧正式 bundle 不得覆盖。
  - 正式 600-step 运行只有在 entry=417、exit=367、pending/dropped/native missing/degraded/active boarding/reserved boarding 全为 0、departed trains=3 且需求守恒时才能发布。
  - 600-step 历史诊断已依次修复共享净距下车放置和入口构造前 FIFO 背压两个运行时缺陷；修复后运行到 600/600，但 exit admitted=195、pending=172。840-step 仅为尾部诊断，exit admitted=197、pending=170，证明延长时长不是解法。

## Step 6：观测-仿真对比
- 产出文件：`src/metro_alignment/metrics/comparison.py`、`scripts/compare_with_simulation.py`、`scripts/run_alignment_scene.py`。
- 验收指标：
  - `data/metrics/comparison_*.json` 包含 `observed` 与 `simulated` 的核心指标与误差。
  - 第一轮门限：步行速度代理中位数相对误差 <= 15%；基本图支持覆盖率 >= 80%，且至少 3 个双方 n>=30 的重叠箱覆盖到 >0.3 人/m²；有支持部分的条件带内占比 >= 80%。
  - bbox proxy 或低全局密度速度代理只允许得到 scientific `hold`，不得写成已标定。
  - comparison 必须能由当前 observed、simulation 和可信 SceneConfig 确定性完整重建；手改顶层 verdict、阈值、支持或 release blocker 均失败。

## Step 7：最终报告
- 产出文件：`src/metro_alignment/report.py`、`docs/DATASETS.md`。
- 验收指标：
  - `docs/DATASETS.md` 每条有效数据集有来源、许可、引用、状态。
  - 报告中输出“参数对照表”字段包含：当前值、观测值、结构化样本支持、来源、建议值与不确定性；scientific hold 时建议值必须保持当前值，观测量仅作为诊断候选。
  - report 参数行和 release decision 必须由当前 comparison 确定性重建；comparison 未同时满足顶层、指标、release blocker 和分析契约资格时，不得授权参数变化。

## Step 8：交付与回滚
- 产出文件：`alignment/README.md`（更新进展）与 `docs/*`。
- 验收指标：
  - 主线仓库无新增数据文件。
- Git 提交消息强制包含 `[alignment]` 前缀（本计划仅提示，执行由开发者操作）。

## Step 9：审查与复核（持续运行）

### 9.1 行业内/论文方法一致性 Agent（审查项）
- [x] free-flow 指标是否显式输出 p5/p25/p50/p75/p95 与 n。
- [x] 基本图是否产出密度-速度分箱，并使用一致单位（m, s）和可复用阈值字段。
- [x] 与 PedPy 方法口径对齐说明是否完整（至少在实现注释/文档中有约束与替代方案）。
- [x] 是否存在 `fundamental_in_band_fraction` 的可解释带宽定义（观测带宽 vs 仿真落点）。

### 9.2 Metro 兼容性 Agent（审查项）
- [x] `run_alignment_scene` 是否固定 `simulation_clock_mode="physical"` 并真实读取 `movement_trace`。
- [x] 是否避免使用 `visual_tracks`，不依赖表现层点位。
- [x] `canonical` 轨迹列是否为 6 列标准：`dataset_id, agent_id, frame, t_s, x_m, y_m`。
- [x] alignment 是否保持不改主线 `metro_station`；当前独立执行因共享 Metro clean-import 回归而被正确阻断。

### 9.3 通用性/反补丁性 Agent（审查项）
- [x] 每个场景配置是否参数化（可复用而非硬编码场景常量）。
- [x] 输出 artifact 的 schema 与主计划 `CANONICAL/metrics` 一致，可多轮跑通。
- [x] 对单一数据/单一场景是否有兜底逻辑；缺失时必须记录为 `pending` 而不是吞掉。

### 9.4 Step1~8 与三方复核的映射（按轮次留档）

- 目标：每轮复核除了三类视角外，逐步补齐 Step1~8 的 Step 级验收证据。
- 对应关系（建议每轮在 `docs/agent_audit_round_N.json` + 逐项证据文件中闭环）：

| Step | 验收指标（精要） | 自动化复核入口 |
|---|---|---|
| Step 1 | 工程初始化、依赖装配、`.gitignore` 生效 | 手工确认 + `uv run python --version` |
| Step 2 | registry 输出和下载幂等 | `python -m metro_alignment.datasets.registry`，`scripts/download_all.py --all` |
| Step 3 | canonical 列、类型、时间单调、坐标与速度范围 | `tests/test_canonical.py`（已编写） + `docs/DATASETS.md` |
| Step 4 | 指标 JSON 存在、含 `low_global_density_walking_speed_proxy_m_s.p50` 与分位数 `n` | `scripts/compute_observed_metrics.py` |
| Step 5 | 仿真场景输出 canonical + movement_trace 映射 | `scripts/run_alignment_scene.py --scene-id ...` |
| Step 6 | 对比文件含观察/仿真核心指标与误差，落带判据有阈值 | `scripts/compare_with_simulation.py` |
| Step 7 | 报告字段含 `当前值/观测值/样本量/建议值` | `src/metro_alignment/report.py` + `docs/DATASETS.md` |
| Step 8 | 交付文档/报告与主仓库隔离约束 | `README.md` + 目录约束 |
| 9.1 | 方法审视点（是否论文口径） | `agent_code_review.py` |
| 9.2 | 与 Metro 兼容点（physical clock / movement_trace） | `agent_metro_compatibility.py` |
| 9.3 | 通用性与反补丁点（schema一致、参数化、待填标记） | `agent_generality.py` |

## 每轮复核触发方式

每一轮按 `A=方法审查 / B=Metro配合 / C=通用性` 三方视角输出：
- 已通过项（Pass）
- 未满足项（Fail）
- 风险项（Risk）及修复建议

可按需求多轮触发：
- 第 1 轮：基线现状 + 快速差距
- 第 2 轮：修复后重检 + 回归风险复核
- 第 3 轮：发布前定点复核

### 执行命令

`uv run python scripts/run_alignment_agent_checks.py --round 1 --out docs/agent_audit_round_1.json`
