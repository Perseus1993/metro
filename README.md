# Metro Data Warehouse and Station Simulation Workspace

西安地铁客流与天气影响分析项目。当前数据流已经收敛为一条固定链路：

```text
raw reports / weather API
  -> staging CSV: data/processed/
  -> ODS facts and dimensions: data/ods/
  -> ADS analysis panels: data/ads/
  -> analysis scripts and outputs
```

## Hard Rule

分析脚本必须通过 `scripts.ods.ods_reader.ODS` 读取数据，例如 `ODS.station_panel()`、`ODS.section_panel()`、`ODS.network_panel()`、`ODS.od_network_panel()`。

禁止分析脚本直接读取 `data/processed/*.csv`。`data/processed/` 是 staging 层，只允许 ETL 和 ODS fact 构建脚本使用。

## Directory Layout

- `scripts/etl/`: 原始报表/API 到 staging CSV 的 ETL 脚本。
- `scripts/ods/`: ODS/ADS 构建和统一读取入口。
- `scripts/analyze_*.py`: 研究分析脚本，默认读取 ADS/ODS。
- `src/metro_data_warehouse/`: 站点、POI、网络和 ODS/ADS 数据访问库。
- `packages/metro_station/`: 正式站内客流仿真包，包含纯领域、应用用例和 Mesa/JuPedSim 适配器。
- `apps/station_designer/`: 独立站型设计器应用及静态资源。
- `apps/station_visualizer/`: 独立动画、回放和录制应用。
- `experiments/metro_station_experiments/`: 批量实验和轨迹证据分析。
- `quality/metro_station_testkit/`: 可复用的确定性探针与微场景。
- `quality/metro_station_acceptance/`: 跨布局与运营验收工具。
- `sandbox/metro_station_sandbox/`: 旧导入路径的薄兼容层，不再拥有生产实现。
- `tests/`: 轻量单元/集成测试，覆盖仿真图编译、显式连通校验、出站/换乘闭环和渲染 payload。
- `data/processed/`: staging CSV，中间层，大文件，不入 git。
- `data/ods/`: ODS Parquet 和 manifest，可由 ETL staging 重建。
- `data/ads/`: ADS Parquet，可由 ODS 重建。
- `data/analysis/`: 分析产出，不入 git。

## Build

生成或刷新 ODS/ADS：

```bash
python scripts/ods/build_ods.py
```

只刷新 ADS：

```bash
python scripts/ods/build_ods.py --only ads
```

ETL 默认路径集中在 `scripts/etl/paths.py`。如需重跑 staging CSV，优先使用 `scripts/etl/` 下的脚本，不要在分析脚本中临时读取原始 Excel 或 staging CSV。

## Test

安装锁定环境（包括正式 `metro-station` 包）：

```bash
uv sync --locked --all-extras --all-packages
```

运行全量测试：

```bash
uv run --no-sync pytest -q
```

运行约束生成布局的静态几何、拓扑、回放和资产绑定验收：

```bash
uv run --no-sync python scripts/run_layout_acceptance.py \
  --tier smoke \
  --generated-count 64 \
  --generated-simulation-samples 0
```

按 `smoke/nightly/release` 档位运行完整生成语料和分层仿真抽样：

```bash
uv run --no-sync python scripts/run_layout_acceptance.py \
  --tier smoke \
  --generated-profile
```

生成语料只保存 recipe、seed 和失败设计；成功场景可由 recipe 重建，不把数千份设计快照提交到仓库。

正式入口：

```bash
uv run --no-sync metro-station simulate --help
uv run --no-sync metro-station validate-design --design-template visual_demo_station
uv run --no-sync metro-station-designer --port 8766
uv run --no-sync metro-station-visualizer --port 8765
```

架构边界和迁移决策记录在 [`docs/architecture/`](docs/architecture/)；CI 通过
Import Linter 阻止新增的反向依赖。当前登记的迁移期例外只能减少，不能增加。

旧命令仍由兼容层转发：

```bash
python -m sandbox.metro_station_sandbox.app
```
