# Metro Data Warehouse

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
- `src/`: 地铁站点、POI、高德网络等可复用业务代码。
- `sandbox/metro_station_sandbox/`: 地铁站内客流仿真沙盒，包含 StationDesignDocument、StationGraph、Mesa agent、JuPedSim backend 和 HTML 可视化。
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

运行当前轻量测试：

```bash
python -m unittest discover -s tests
```

运行 Mesa+JuPedSim 站内仿真，并导出 `animation_demo.html` 使用的可视化数据：

```bash
python -m sandbox.metro_station_sandbox.app
```
