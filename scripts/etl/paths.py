"""ETL path configuration for raw and staging data."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Raw reports exported from the operations folders.
RAW_REPORTS_ROOT = PROJECT_ROOT / "data" / "BaiduNetdiskDownload" / "运营数据" / "三"
RAW_STATION_REPORTS = RAW_REPORTS_ROOT / "线路分时段客运量统计报表"
RAW_SECTION_REPORTS = RAW_REPORTS_ROOT / "线路各区间期间分时断面流量汇总表"
RAW_OD_REPORTS = RAW_REPORTS_ROOT / "线网OD统计分析报表"

# Raw Open-Meteo outputs.
RAW_WEATHER_DIR = PROJECT_ROOT / "data" / "weather" / "open_meteo"
RAW_WEATHER_HOURLY_CSV = RAW_WEATHER_DIR / "open_meteo_xian_center_2025-01-01_2025-06-30_hourly.csv"

# Staging CSV layer. ODS builders may read this; analysis scripts must not.
STAGING_DIR = PROJECT_ROOT / "data" / "processed"
STAGING_STATION_FLOW_30MIN = STAGING_DIR / "station_flow_30min_2025H1.csv"
STAGING_SECTION_FLOW_15MIN = STAGING_DIR / "section_flow_15min_2025H1.csv"
STAGING_OD_NONZERO_60MIN = STAGING_DIR / "od_nonzero_60min_2025H1.csv"
STAGING_OD_NETWORK_HOURLY = STAGING_DIR / "od_network_hourly_2025H1.csv"
STAGING_WEATHER_HOURLY_LABELED = STAGING_DIR / "weather_hourly_labeled_xian_center_2025H1.csv"
STAGING_CALENDAR_LABELS = STAGING_DIR / "calendar_labels_2025H1.csv"
