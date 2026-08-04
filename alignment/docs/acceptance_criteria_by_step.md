# Alignment Step 1–8 可执行验收标准

更新：2026-08-04。唯一聚合入口：

```powershell
uv run --project . python scripts/verify_acceptance.py `
  --out docs/acceptance_latest.json
```

默认退出码只代表“实现门”是否通过；增加 `--require-release` 后，Step 6 的科学标定门也必须通过。验收状态严格区分：

- `implemented`：代码路径存在；
- `tested`：行为/反例测试通过；
- `demonstrated`：真实数据或真实 Metro 运行产物通过契约；
- `proposed/pending`：尚无足够实现或证据，不能写成通过。

## Step 1 基础工程化

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 独立依赖锁 | `uv lock --check --project .` exit 0 | `pyproject.toml`, `uv.lock` |
| 独立导入 | `metro_alignment`、`metro_station`、`pedpy` 均可导入 | verifier Step 1 |
| 干净进程入口 | 新 Python 子进程执行 `scripts/run_alignment_scene.py --list-scenes` exit 0，不能依赖 pytest/import cache 的加载顺序 | `tests/test_clean_process_entrypoint.py` |
| 主线隔离 | 根 `pyproject.toml` 无需修改 | Git diff |

## Step 2 数据注册与下载

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 元数据 | 每条数据集 `license/citation/status` 非空；至少 1 条 `active` | registry JSON |
| pending 语义 | pending 数据集下载/构建必须显式非零失败，不得返回空成功 | registry/download tests |
| 续传 | mock `206 + Content-Range` 正确 append；服务器忽略 Range 回 `200` 或回 `416` 时，先把完整响应写入独立 restart 文件，校验成功后再替换；失败时旧 partial 保留 | `tests/test_download.py` |
| 幂等 | MD5 已通过时网络调用数为 0、`skipped=true` | `tests/test_download.py` |

## Step 3 Canonical 统一格式

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| schema | 列和顺序严格为 `dataset_id,agent_id,frame,t_s,x_m,y_m`；dtype 严格匹配 | tests + Parquet schema |
| 标识与数值 | `dataset_id` null=0 且单值；ID/frame 非负；时间/坐标有限 | tests + row-group stats |
| 时间 | 每个 agent 的 `diff(t_s) > 0`；重复 `(agent_id,t_s)=0` | full-build validation metadata |
| 失败语义 | 空输入、坏 ID、缺/多列、重复时间均非零失败且不落盘 | `tests/test_canonical.py` |
| 真实证据 | Eindhoven meta `row_count == Parquet rows` 且记录 full validation | verifier Step 3 |

## Step 4 观测侧指标

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 单一算法 | 大/小数据均调用同一 PedPy 管线，不存在 `>50k` 语义 fallback | source + mutation tests |
| 速度代理 | 实际调用 `compute_individual_speed:BORDER_SINGLE_SIDED`；物理速度窗口固定为双方一致的 `0.4s`；`n>=30`；p5/p25/p50/p75/p95 有限且有序 | observed JSON 的 analysis contract |
| sanity | 低全局密度、截断后的步行速度代理 `0.5 <= p50 <= 2.5 m/s`；这只是错误哨兵，不是自由流/期望速度标定证据 | verifier Step 4 |
| 密度/基本图 | 显式 MeasurementArea；实际调用 classic density + frame mean speed；bins 非空 | observed JSON |
| 抽样 | 只抽源帧号与源时间都连续的完整 frame 窗；稀疏帧必须截断而不能压紧伪造速度；窗口间 agent identity 分离；行重排结果不变 | `tests/test_sampling.py` + sampling provenance |
| 契约一致性 | analysis contract 的 PedPy 版本、速度步长/物理窗、密度方法、阈值、分箱和多边形 shape hash 必须与实际 method/config 逐项一致 | mutation tests + verifier/agent |
| 实际贡献支持 | 速度代理与基本图分别记录真实 point/agent/frame/window/source-canonical-row；数量关系和 metric n 必须可对账 | observed v5 `metric_support` |
| 新鲜度 | canonical 与 meta 的相对路径、size、SHA-256 以及 analysis runtime 指纹在计算前后保持一致 | observed v5 + verifier |

## Step 5 Metro 仿真轨迹对齐

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 真值源 | 仅接受 `movement_trace.v1` 或 `simulation_trace.v1.movement_trace`；authority 属于 Metro 声明集合；拒绝 visual-only | `tests/test_metro_trace.py` |
| scope | 指标输入 100% 为 `phase=walking` | trace provenance |
| episode | `(passenger_id,episode_id)` 映射到 `agent_id>=90,000,000`；重复/非正时间差为 0 | seam tests + real run |
| raw 类型 | passenger 必须为非 bool 整数、episode 必须为非空字符串、time/x/y 必须为有限 JSON 数值 | strict trace counterexamples |
| 采样时钟 | trace `sample_interval_seconds` 与可信 SceneConfig 精确一致（绝对容差 `1e-12`） | producer/verifier/agent mismatch tests |
| seed | CLI seed、`SimulationRequest.seed`、manifest seed 三者相同 | manifest + real run |
| 可移植证据 | artifact 仅相对路径，SHA-256/size 校验通过 | verifier Step 5 |
| 回放配置 | 当前 `SceneConfig` 与 manifest 的 schema、完整键集合、全部值和 SHA-256 必须完全一致 | `tests/test_metro_contract.py` |
| 运行时 | Metro Python 源树与 Python/关键依赖版本指纹必须匹配当前环境 | runtime fingerprint + verifier |
| 写盘竞态 | Metro 与 alignment analysis 的运行开始指纹必须贯穿仿真、轨迹转换和 PedPy 计算；最终复核前不写正式 evidence | runner source + source-change gate |
| 实际贡献支持 | 每个指标分别记录真实 point/episode/passenger/frame/seed，且与 metric n/FD frame n 可对账 | simulation v5 `metric_support` |
| 独立重建 | 从同一已哈希 movement-trace bytes 重新解析所得 canonical/provenance/metrics/support/summary 必须与落盘证据逐项完全一致；当前 DesignDocument 必须能由 Metro 编译 | verifier + Metro compatibility agent |
| 场景几何 | platform 尺寸改变必须改变 DesignDocument hash，尺寸误差 `<=0.01m` | `tests/test_scenes.py` |
| 源区预检 | 必须在 `build_model` 前，用 SceneConfig 生成的 DesignDocument、场景共享 `radius*clearance_multiplier`、DemandScheduler 峰值同 tick 下车批次和实际完整候选窗口检查 holding area、其净距缓冲区、门轴通道及候选唯一性；冲突还必须由 Metro 编译器复现为 `capacity.coactive_slot_conflict` | `alignment_source_geometry_preflight.v3` + tests |
| 失败关闭 | 任一源区冲突必须输出当前 config/design/Metro/analysis 指纹绑定的结构化 artifact，标记 `runtime_status=not_started`、`scientific_status=model_invalid`、`release_eligible=false`；不得称为容量超限 | `platform_boarding_source_preflight.json` + verifier Step 5 |
| 需求与列车守恒 | 正式 600-step 必须 entry=417、exit=367、pending/dropped/native missing/degraded/active boarding/reserved boarding 全为 0，departed trains=3，请求量=计划量 | runner publication gate + replay-bypass tests |

当前场景边界：`platform_boarding` 为 Eindhoven bbox 尺寸代理；内部障碍/门位仍是 proxy。设计文档级预检测得共享净距 0.396 m、峰值同 tick 下车批次 4、候选窗口 67，其中 holding area 内 60、净距缓冲内 64、门轴冲突 4，故 Step 5 是 `model_invalid / source_geometry_conflict`，runtime 不启动。历史诊断中，修复第 327 步共享净距放置与第 558 步入口原子准入后，600-step 完成但 exit admitted/pending=195/172；840-step 尾部诊断仅改善为 197/170。840 不是新基线，也不能支持容量结论。通用修复需要 Metro core 提供 train-specific exchange manifest、同一 PTI 控制器、下车优先或已标定混合策略、共享通道预约及有界 deadlock/hold。`corridor_unidirectional` 与 `bottleneck` 仍因 Metro 主线最小 gate/queue 几何约束为 `pending`。

## Step 6 观测—仿真对比（科学发布门）

| 指标 | 通过阈值 | 失败语义 |
|---|---:|---|
| 分析契约 | PedPy 版本、0.4s 速度窗口、密度算法、代理阈值、分箱边、共享坐标帧和测量多边形 hash 必须完全一致 | 任一不同则所有比较项 `unavailable` |
| 步行速度代理中位数 | `abs(relative_error) <= 0.15` | observed=0/空样本为 `unavailable`；不得写成自由流或期望速度标定通过 |
| 基本图支持覆盖 | simulated frame 的观测支持覆盖率 `>=0.80`，且双方 `n>=30` 的重叠箱 `>=3`、密度上界必须超过 `0.3 persons/m²` | 不足为 `unavailable`，不能用低密度小片段冒充基本图通过 |
| 基本图条件落带 | 在已有观测支持的箱内，按 simulated frame n 加权的 p5–p95 带内比例 `>=0.80` | 与 support coverage 分开报告；无重叠为 `unavailable` |
| 反例 | 明显带外=0，带内=1，5/5 混合=0.5 | `tests/test_metrics.py` |
| 总门 | 速度代理、FD 支持覆盖、FD 条件落带三项均 `within_band` 且无发布 blocker，才 `overall_verdict=pass` | 否则 release=`hold` |
| 几何资格 | 仿真场景必须 `geometry_evidence_status=observed_matched` | bbox/internal-layout proxy 即使数值过线也强制 release=`hold` |
| 防伪重算 | 整份 comparison 必须与当前 observed、simulation、可信 SceneConfig 和输入 SHA-256 的确定性重建完全相等 | builder + verifier + forged-verdict test |

Step 6 的 `hold` 表示软件闭环可执行但标定/验证没有成功，不能用“产物存在”替代门限。

## Step 7 参数报告

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 字段 | current/observed/sample_support/source/suggestion/status/uncertainty/evidence 全部存在；sample_support 分别记录点、agent/window 与 episode/passenger/seed | `parameter_report_{scene_id}.json` |
| 诚实状态 | Step 6 hold 时只能写 `candidate_not_validated` | `tests/test_report.py` |
| 参数授权 | Step 6 hold 时 `suggestion == current_value`；观测代理只可放在 `diagnostic_candidate_value`，且 `parameter_change_authorized=false` | `tests/test_report.py` |
| 来源 | comparison 校验并记录 observed/simulation 当前 SHA-256；report 另记录并校验当前 comparison SHA-256；任何旧链路不得通过 fresh acceptance | comparison/report JSON + verifier |
| 防伪重算 | report 行、建议值、授权位和 release decision 必须能从安全解析的 ready-scene comparison 完整重建；仅改顶层 pass 或参数行失败 | report validator + verifier |

## Step 8 交付与隔离

| 指标 | 通过阈值 | 证据 |
|---|---:|---|
| 大文件隔离 | 每个 active dataset 的全部注册 raw、canonical、parquet、`*.movement_trace.json` 被 ignore | `.gitignore` + `git check-ignore` |
| 防伪执行 | `--skip-tests` 必须快速输出 hold/非零；正式验收前后 analysis、Metro、scripts/tests 指纹完全一致并写入 acceptance | verifier tests + acceptance JSON |
| 代码质量 | `uv run --project . ruff check .` exit 0 | verifier Step 8 |
| 回归 | `uv run --project . python -m pytest -q` 全过 | verifier Step 8 |
| 写边界 | 本计划实现只写 `alignment/` | Git diff |

## Step 9 三方独立复审

每轮在代码与真实证据更新后触发，不允许复用旧结论：

1. 方法 Agent：PedPy/论文方法、measurement geometry、采样与统计门；
2. Metro Agent：官方 trace schema、phase/episode/seed、布局编译和可移植 manifest；
3. 通用性 Agent：重复时间、零基线、空 bins、坏输入、行重排、参数变形等反例。

每个 Agent 输出 `P0/P1/P2 + 文件/行 + 复现 + 通用修复 + 量化验收`。P0/P1 修复后必须触发下一轮；旧 round 若早于源码/产物即为 stale。
