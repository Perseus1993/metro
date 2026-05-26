"""Build dim_weather_hourly.parquet — 天气维表。

从 Open-Meteo hourly CSV 加工 weather labels 后输出 Parquet。
复用 scripts/etl/build_weather_labels.py 的标签逻辑。
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


# ─────────────────────────────────────────────
# Precipitation grading (固定阈值方案)
# ─────────────────────────────────────────────
def _precip_grade(precip_mm: float) -> str:
    if precip_mm <= 0:
        return "no_rain"
    if precip_mm < 2.5:
        return "light_rain"
    if precip_mm < 8.0:
        return "moderate_rain"
    if precip_mm < 16.0:
        return "heavy_rain"
    return "rainstorm"


def _precip_quantile_grade(precip: float, p50: float, p90: float) -> str:
    if precip <= 0:
        return "no_rain"
    if math.isnan(p50) or math.isnan(p90):
        return "rain_ungraded"
    if precip <= p50:
        return "rain_low"
    if precip <= p90:
        return "rain_mid"
    return "rain_high"


def _is_normal_weather(precip: float, temp: float, ws: float, wg: float) -> bool:
    if precip > 0:
        return False
    if temp >= 35:
        return False
    if temp <= 0:
        return False
    if ws >= 10.8 or wg >= 13.9:
        return False
    return True


def build(
    input_csv: str | Path = (
        "data/weather/open_meteo/open_meteo_xian_center_2025-01-01_2025-06-30_hourly.csv"
    ),
    output_path: str | Path = "data/ods/dim_weather_hourly.parquet",
) -> pd.DataFrame:
    input_csv = Path(input_csv)
    output_path = Path(output_path)

    df = pd.read_csv(input_csv, encoding="utf-8-sig")
    # 规则 10: CSV 列名读入后必须 strip()
    df.columns = df.columns.str.strip()

    # Parse time
    df["datetime"] = pd.to_datetime(df["time"])
    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour.astype("int32")

    # Float columns
    float_cols = [
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "rain",
        "pressure_msl",
        "cloud_cover",
        "wind_speed_10m",
        "wind_gusts_10m",
    ]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    if "weather_code" in df.columns:
        df["weather_code"] = pd.to_numeric(df["weather_code"], errors="coerce").astype("Int32")

    # Compute quantile thresholds
    precip = df["precipitation"].fillna(0.0)
    nonzero = precip[precip > 0].sort_values()
    if len(nonzero) >= 2:
        p50 = nonzero.iloc[int(len(nonzero) * 0.5)]
        p90 = nonzero.iloc[int(len(nonzero) * 0.9)]
    else:
        p50, p90 = math.nan, math.nan
    print(f"[AUDIT] precip_nonzero_hours={len(nonzero)} P50={p50:.3f} P90={p90:.3f}")

    # Compute flags
    p = precip.values
    t = df["temperature_2m"].fillna(0).values
    ws = df["wind_speed_10m"].fillna(0).values
    wg = df["wind_gusts_10m"].fillna(0).values

    df["rain_flag"] = (p > 0).astype("int8")
    df["light_rain_flag"] = ((p > 0) & (p < 2.5)).astype("int8")
    df["moderate_rain_flag"] = ((p >= 2.5) & (p < 8.0)).astype("int8")
    df["heavy_rain_flag"] = ((p >= 8.0) & (p < 16.0)).astype("int8")
    df["rainstorm_flag"] = (p >= 16.0).astype("int8")
    df["hot_flag"] = (t >= 35).astype("int8")
    df["very_hot_flag"] = (t >= 38).astype("int8")
    df["freezing_flag"] = (t <= 0).astype("int8")
    df["windy_flag"] = ((ws >= 10.8) | (wg >= 13.9)).astype("int8")

    df["precip_grade"] = precip.apply(_precip_grade)
    df["precip_quantile_grade"] = precip.apply(lambda x: _precip_quantile_grade(x, p50, p90))
    df["is_normal_weather"] = [
        int(_is_normal_weather(pp, tt, wws, wwg)) for pp, tt, wws, wwg in zip(p, t, ws, wg)
    ]
    df["is_normal_weather"] = df["is_normal_weather"].astype("int8")

    df["source_batch"] = "weather_openmeteo_v2"

    # Select output columns
    out_cols = [
        "date",
        "hour",
        "datetime",
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "rain",
        "weather_code",
        "pressure_msl",
        "cloud_cover",
        "wind_speed_10m",
        "wind_gusts_10m",
        "rain_flag",
        "light_rain_flag",
        "moderate_rain_flag",
        "heavy_rain_flag",
        "rainstorm_flag",
        "hot_flag",
        "very_hot_flag",
        "freezing_flag",
        "windy_flag",
        "precip_grade",
        "precip_quantile_grade",
        "is_normal_weather",
        "source_batch",
    ]
    out = df[out_cols].copy()

    # Assertions
    pk = out[["date", "hour"]].apply(tuple, axis=1)
    assert pk.is_unique, "(date, hour) not unique in dim_weather_hourly!"

    flag_summary = {col: int(out[col].sum()) for col in out.columns if col.endswith("_flag")}
    print(f"[AUDIT] dim_weather_hourly: rows={len(out)} flags={flag_summary}")

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False, engine="pyarrow")
    fsize_kb = output_path.stat().st_size / 1024
    print(f"[AUDIT] dim_weather_hourly written: {output_path} ({fsize_kb:.1f} KB)")

    return out


if __name__ == "__main__":
    build()
