# Alignment 第7轮执行摘要（基于 `alignment` 子目录）

## 目标与范围
- 完成 `PLAN.md` 中 Step 1~8 的闭环复核，并保留三类复核 Agent 的多轮触发记录。
- 所有改动仍仅在 `alignment/` 目录内完成。

## Step 1：基础工程化（执行状态）
- `alignment/pyproject.toml` 与 `alignment/.gitignore` 已存在且可复用。
- 验收执行命令：
  - `uv run python -m metro_alignment.datasets.registry`
  - `uv run python -m pip show pedpy`（运行环境下）

## Step 2：数据集注册与下载
- `src/metro_alignment/datasets/registry.py` 已支持统一字段：
  - `license`、`citation` 非空校验在 `DatasetSpec.__post_init__`。
  - `raw_loader_ref`、`to_canonical_ref`、`agent_id_offset` 已加入。
  - 统一入口解析函数 `resolve_reference(ref: str)` 已加入。
- `download.py`/`download_all.py` 走 `download_file` 全链路：
  - `Range` 断点续传已实现（`Range` 头 + `.partial` 写入）。
  - 非支持 `Range` 时降级全量重下。
  - MD5 校验通过/失败分支存在。
- 验收执行命令：
  - `uv run python -m metro_alignment.datasets.registry`
  - `uv run python scripts/download_all.py --all`

## Step 3：Canonical 统一格式
- `registry.py` 与 `build_canonical.py` 解耦了数据集前缀硬编码：
  - `build_canonical.py` 全量改造为通过 `spec.raw_loader_ref` 和 `spec.to_canonical_ref` 动态加载。
  - `CANONICAL_COLUMNS` 与 `CANONICAL_SCHEMA_VERSION` 仍为固定 schema。
- 验收执行命令：
  - `uv run python -m metro_alignment.datasets.registry`
  - `uv run python scripts/run_alignment_agent_checks.py --round 7 --agent generality`

## Step 4：指标计算（观测侧）
- `compute_observed_metrics.py` 输出 `data/metrics/{dataset_id}_observed.json`。
- 指标 JSON 中 `free_flow_speed_m_s` 包含 `p5/p25/p50/p75/p95` 与 `n`。
- `scripts/fundamental.py` 保持 `speed` 与 `fundamental_diagram` 结构。
- 验收执行命令（示例）：
  - `uv run python scripts/compute_observed_metrics.py --dataset-id demo --input data/canonical/demo.parquet`

## Step 5：仿真轨迹可对齐
- `scripts/run_alignment_scene.py` 保持 `movement_trace()` + `simulation_clock_mode="physical"` + `movement_backend_name="jupedsim"`。
- `visual_only` 点过滤、`movement_trace` 映射为 canonical 字段已实现。
- 验收执行命令：
  - `uv run python scripts/agent_metro_compatibility.py --round 7`
  - `uv run python scripts/run_alignment_scene.py --help`

## Step 6：观测-仿真对比
- `compare_with_simulation.py` 输出 `data/metrics/comparison_{scene_id}.json`，结构包含：
  - 观测指标、仿真指标、相对误差、判定。
  - `fundamental_in_band_fraction` 基于 `fundamental_in_band_fraction(...)` 聚合输出。
- 验收执行命令（示例）：
  - `uv run python scripts/compare_with_simulation.py --scene-id ...`

## Step 7：最终报告
- `report.py` 仍提供统一参数表导出链路：`parameter`/`current_value`/`observed_value`/`sample_size`/`source`/`suggestion`。
- `docs/DATASETS.md` 完成了数据集清单、license 与状态同步更新。

## Step 8：交付与回滚
- 交付文件当前包含：
  - `alignment/README.md`
  - `alignment/docs/*`（含本轮审计文件）
  - `alignment/data/metrics/*.json`（可交付小文件）
- `alignment/.gitignore` 已屏蔽 `data/raw`、`data/canonical`、`notebooks`。

## 三类 Agent 复核（多轮）
- round 6：已归档为 `alignment/docs/agent_*_round_6.json` 且均为 `pass`。
- round 7：已执行，汇总到 `alignment/docs/agent_audit_round_7.json`，全部 `pass`。

## 当前建议
1. 维持 `round 7` 作为当前基线快照；后续每次新增场景/新数据都触发一次新 round。
2. 数据接入正式上线前，建议把 stub 条目替换为真实 `_files` 与真实加载/转换配置，再触发 `round 7 -> 8`。
