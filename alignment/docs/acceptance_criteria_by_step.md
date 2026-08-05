# Alignment Step 1–8 可执行验收标准

更新：2026-08-05。唯一聚合入口：

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
| 当前留痕 | preflight 无论通过或失败都必须输出 v2 artifact 并绑定当前 config/design/Metro/analysis 指纹；通过时记录 `runtime_status=ready`、`scientific_status=eligible`，但 preflight 本身不得授权 release | `run_alignment_scene.py --preflight-only` + verifier Step 5 |
| 失败关闭 | 任一源区冲突必须在 v2 artifact 中标记 `runtime_status=not_started`、`scientific_status=model_invalid`、`release_eligible=false`；不得称为容量超限 | `platform_boarding_source_preflight.json` + verifier Step 5 |
| 最终指纹阶梯 | 机制修复冻结后，`exit-only 350 -> entry-only 600 -> mixed 600` 必须按此顺序在同一 SceneConfig、Design、Metro source、analysis source 和依赖指纹下一次性重跑；任一中途源码/配置变化使整组证据 stale，必须从 exit-only 重新开始 | 版本化 ladder manifest + 每段 control artifact；禁止混用 `.codex_tmp` 或旧 round 诊断 |
| 正式运行与发布边界 | 阶梯必须由 `scripts/run_alignment_scene.py` 的正式 control/profile 路径执行；只有通过全部前置门的 mixed 600 可调用内容寻址、原子 manifest 切换的发布器。临时脚本、手动 `model.step()`、trace replay 或诊断 JSON 不得成为发布 bundle | runner CLI、原子发布测试、runner provenance |
| 需求与列车守恒 | 正式 600-step 必须 entry=417、exit=367、pending/dropped/native missing/degraded/active boarding/reserved boarding 全为 0，departed trains=3，请求量=计划量 | runner publication gate + replay-bypass tests |
| 入口断面容量带检 | 与最终阶梯相同冻结指纹下，另跑预注册的 entry-tail 饱和断面 control；固定测量线、有效净宽、饱和判据和时间窗，稳定窗口比流量必须在 `1.2 <= q/(w*t) <= 1.5 persons/(m*s)`。低于下沿表示机制过紧，高于上沿表示回收/避碰过松，均阻断 Step 5。正式 417 人需求的 600 秒全程均值不作为容量带检，因为其最大可能值仅为 `417/(600*1.6)=0.434 persons/(m*s)` | 版本化 saturated-flow artifact + 双边反例；分母和窗口不得按结果后调 |

最终指纹 ladder manifest、正式 control/profile 和 saturated-flow artifact 现已达到
`implemented/tested`：严格的 `alignment_ladder_manifest.v1` schema、正式 profile runner、
预注册 entry-tail 测量合同、`1.2～1.5` 双边反例、阶梯级原子 pointer 切换与故障回滚均有
自动化测试。它们尚未在学弟 2 的最终 Metro 机制修复指纹上完成真实阶梯，因此仍不是
`demonstrated` 证据；Step 5 在新的 ladder/saturated artifact 真正发布前继续 fail-closed。

正式入口：

```powershell
uv run --project . python scripts/run_alignment_scene.py `
  --scene-id platform_boarding `
  --profile alignment_step5_final.v1 `
  --output data/metrics/platform_boarding_simulated.parquet
```

该 profile 内部顺序固定为 `exit-only-350 -> entry-only-600 ->
entry-tail-saturated-flow -> mixed-600`；前三段不得切换正式 simulation v5 pointer。

当前场景边界：`platform_boarding` 为 Eindhoven bbox 尺寸代理；内部障碍/门位仍是 proxy。Round 23 将下车源点阵横向错开 10.0 m；设计文档级预检保持共享净距 0.396 m、峰值同 tick 下车批次 4、候选窗口 67，并把 holding area、净距缓冲和门轴冲突全部降为 0。正式 600-step 已完成，但发布守恒门测得 entry admitted/pending=361/56、exit admitted/pending=170/197，故 Step 5 仍 fail，失败阶段已从构模前 `source_geometry_conflict` 推进到运行后 `admission_acceptance_failed`。随后同源诊断证明下车侧可清空，而当前源码指纹下 entry-only 仍为 319/417、98 pending；这些数字和比流量审计只用于定位，任何机制修复改变 Metro source fingerprint 后即全部 stale。840-step 历史诊断不是新基线，也不能支持容量结论。后续通用修复仍需要 train-specific exchange manifest、同一 PTI 控制器、下车优先或已标定混合策略、共享通道预约及有界 deadlock/hold。`corridor_unidirectional` 与 `bottleneck` 仍因 Metro 主线最小 gate/queue 几何约束为 `pending`。

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
| 独立 holdout / 多种子 | 候选选择前冻结 calibration/holdout split、输入 SHA 和零重叠证明；固定至少 10 个种子，10/10 先过 Step 5，聚合 95% CI 相对半宽 `<=5%` 且 `converged=true` | 缺 split、逐种子内容寻址产物、收敛计算或任一种子失败均保持 `candidate_not_validated` |
| 防伪重算 | 整份 comparison 必须与当前 observed、simulation、可信 SceneConfig 和输入 SHA-256 的确定性重建完全相等 | builder + verifier + forged-verdict test |

Step 6 的 `hold` 表示软件闭环可执行但标定/验证没有成功，不能用“产物存在”替代门限。
Step 5 的 mixed 600 与饱和断面 control 通过只允许生成新的 simulation v5；它不等于 release。当前 geometry=`proxy`、独立 holdout 和多种子收敛证据缺失时，Step 6 必须继续 `hold`。
顺序固定为：先修机制并完成最终指纹阶梯，再用新 simulation 重建 comparison；只有误差仍存在时才重新讨论 `jupedsim_desired_speed_mps`。当前 1.22 不因旧 v2 的 1.130232 诊断而改变。seeds 41--50 的十个 600-step holdout 与 scale-soak 进入 nightly 档位，不作为每次提交门。

2026-08-05 已冻结数据 split：calibration=`days 01-10`，holdout=`days 11-20`。全量扫描发现原始文件在时间上完全分离，但有一个跨边界 ID `4523217`；因此有效 holdout 合同明确排除所有 calibration ID，并在 `calibration_holdout_split_eindhoven_platform_v1.json` 中同时保留原始交集、排除清单、两份输入 SHA-256 与有效零重叠证明。holdout outcome 在候选冻结前不得计算。

多种子聚合器固定接受且只接受 seeds 41--50 的 simulation v5 内容寻址 manifest；十个运行必须共享去除 seed 后的 SceneConfig、Design、Metro runtime 与 analysis 指纹并逐个满足 Step 5 最终计数。收敛统计使用 df=9 的 Student-t 95% CI，`half_width / abs(mean) <= 0.05` 才置 `converged=true`。`legacy_single_run_replay_smoke` 仅调通序列化与计算路径，即使重复值给出零半宽也必须保持 `converged=false`、`gate_status=smoke_only`。

seeds 41--50 与四类重场景 scale-soak 已进入
`.github/workflows/scientific-nightly.yml` 的 schedule/workflow_dispatch 长任务档位；PR/push
smoke 不承担该预算。nightly seed manifest 还必须声明正式 profile provenance，trace replay 或
手工 `model.step()` 产物不能进入聚合。

```powershell
uv run --project . python scripts/freeze_calibration_holdout_split.py
uv run --project . python scripts/aggregate_multi_seed.py --input-dir <new-bundle-root> --out data/metrics/multi_seed_platform_boarding.json
```

几何资格由 [ADR-009](../../docs/architecture/ADR-009-alignment-geometry-evidence-qualification.md) 裁决：现有 `entrance_a` 不得部分升级，geometry 继续 `proxy`。

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
| 写边界 | 对齐专属逻辑留在 `alignment/`；编译证书与 runtime 共用的几何参数只允许最小修改 `packages/metro_station/` 对应契约并补根回归 | Git diff + root targeted tests |

## Step 9 三方独立复审

每轮在代码与真实证据更新后触发，不允许复用旧结论：

1. 方法 Agent：PedPy/论文方法、measurement geometry、采样与统计门；
2. Metro Agent：官方 trace schema、phase/episode/seed、布局编译和可移植 manifest；
3. 通用性 Agent：重复时间、零基线、空 bins、坏输入、行重排、参数变形等反例。

每个 Agent 输出 `P0/P1/P2 + 文件/行 + 复现 + 通用修复 + 量化验收`。P0/P1 修复后必须触发下一轮；旧 round 若早于源码/产物即为 stale。
