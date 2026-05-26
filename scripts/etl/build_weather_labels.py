"""Build hourly weather disturbance labels for metro analysis.

Upgrades over v1:
  - Full precipitation grading: no_rain / light_rain / moderate_rain / heavy_rain / rainstorm
  - Multi-label flags (NOT mutually exclusive): rain + hot + windy can co-occur
  - Quantile-based precipitation grouping (computed from non-zero precip hours)
  - Unified naming: freezing (was cold/freezing_or_below)
  - is_normal_weather flag for matching candidate identification
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.etl.paths import (  # noqa: E402
    RAW_WEATHER_HOURLY_CSV,
    STAGING_WEATHER_HOURLY_LABELED,
)


def to_float(value: str | None, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


# ─────────────────────────────────────────────
# Precipitation grading  (固定阈值方案)
# ─────────────────────────────────────────────
def precip_grade(precip_mm: float) -> str:
    """Classify hourly precipitation into fixed-threshold grades."""
    if precip_mm <= 0:
        return "no_rain"
    if precip_mm < 2.5:
        return "light_rain"
    if precip_mm < 8.0:
        return "moderate_rain"
    if precip_mm < 16.0:
        return "heavy_rain"
    return "rainstorm"


# ─────────────────────────────────────────────
# Multi-label weather flags
# ─────────────────────────────────────────────
def compute_flags(
    precip: float,
    temp: float,
    wind_speed: float,
    wind_gust: float,
) -> dict[str, int]:
    """Return multi-label flags; multiple can be 1 simultaneously."""
    return {
        "rain_flag": int(precip > 0),
        "light_rain_flag": int(0 < precip < 2.5),
        "moderate_rain_flag": int(2.5 <= precip < 8.0),
        "heavy_rain_flag": int(8.0 <= precip < 16.0),
        "rainstorm_flag": int(precip >= 16.0),
        "hot_flag": int(temp >= 35),
        "very_hot_flag": int(temp >= 38),
        "freezing_flag": int(temp <= 0),
        "windy_flag": int(wind_speed >= 10.8 or wind_gust >= 13.9),
    }


def is_normal_weather(
    precip: float,
    temp: float,
    wind_speed: float,
    wind_gust: float,
) -> bool:
    """§4.1 definition: normal weather hour (for matching candidates)."""
    if precip > 0:
        return False
    if temp >= 35:
        return False
    if temp <= 0:
        return False
    if wind_speed >= 10.8 or wind_gust >= 13.9:
        return False
    return True


# ─────────────────────────────────────────────
# Quantile grading  (分位数方案, two-pass)
# ─────────────────────────────────────────────
def compute_precip_quantiles(
    precip_values: list[float],
) -> tuple[float, float]:
    """Compute P50 and P90 of non-zero precipitation values.

    Returns (nan, nan) if fewer than 2 non-zero values.
    """
    nonzero = sorted(v for v in precip_values if v > 0)
    if len(nonzero) < 2:
        return (math.nan, math.nan)
    n = len(nonzero)
    p50 = nonzero[int(n * 0.5)]
    p90 = nonzero[int(n * 0.9)]
    return p50, p90


def precip_quantile_grade(precip: float, p50: float, p90: float) -> str:
    """Classify precipitation by sample quantiles."""
    if precip <= 0:
        return "no_rain"
    if math.isnan(p50) or math.isnan(p90):
        return "rain_ungraded"
    if precip <= p50:
        return "rain_low"
    if precip <= p90:
        return "rain_mid"
    return "rain_high"


# ─────────────────────────────────────────────
# Main build
# ─────────────────────────────────────────────
def build_labels(input_csv: Path, output_csv: Path) -> int:
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # --- Pass 1: collect all precipitation values for quantile computation ---
    all_precip: list[float] = []
    with input_csv.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        # 规则 10: CSV 列名读入后必须 strip()
        for row in reader:
            row = {k.strip(): v for k, v in row.items()}
            all_precip.append(to_float(row.get("precipitation")))

    p50, p90 = compute_precip_quantiles(all_precip)
    nonzero_count = sum(1 for v in all_precip if v > 0)
    print(f"[AUDIT] precip_nonzero_hours={nonzero_count} P50={p50:.3f} P90={p90:.3f}")

    # --- Pass 2: write labeled output ---
    fieldnames = [
        "time",
        "date",
        "hour",
        "time_bin_60min",
        # raw weather variables
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
        # multi-label flags (can co-occur)
        "rain_flag",
        "light_rain_flag",
        "moderate_rain_flag",
        "heavy_rain_flag",
        "rainstorm_flag",
        "hot_flag",
        "very_hot_flag",
        "freezing_flag",
        "windy_flag",
        # fixed-threshold grade
        "precip_grade",
        # quantile grade
        "precip_quantile_grade",
        # composite
        "is_normal_weather",
    ]

    rows_written = 0
    flag_counts: dict[str, int] = {}
    with input_csv.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        with output_csv.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                row = {k.strip(): v for k, v in row.items()}
                timestamp = row["time"]
                date_part, hour_part = timestamp.split("T")
                hour = int(hour_part[:2])

                precip = to_float(row.get("precipitation"))
                temp = to_float(row.get("temperature_2m"))
                wind_speed = to_float(row.get("wind_speed_10m"))
                wind_gust = to_float(row.get("wind_gusts_10m"))

                flags = compute_flags(precip, temp, wind_speed, wind_gust)
                grade = precip_grade(precip)
                q_grade = precip_quantile_grade(precip, p50, p90)
                normal = is_normal_weather(precip, temp, wind_speed, wind_gust)

                # Track flag counts for audit
                for k, v in flags.items():
                    if v:
                        flag_counts[k] = flag_counts.get(k, 0) + 1

                output_row = {
                    "time": timestamp,
                    "date": date_part,
                    "hour": hour,
                    "time_bin_60min": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                    "temperature_2m": row.get("temperature_2m", ""),
                    "relative_humidity_2m": row.get("relative_humidity_2m", ""),
                    "apparent_temperature": row.get("apparent_temperature", ""),
                    "precipitation": row.get("precipitation", ""),
                    "rain": row.get("rain", ""),
                    "weather_code": row.get("weather_code", ""),
                    "pressure_msl": row.get("pressure_msl", ""),
                    "cloud_cover": row.get("cloud_cover", ""),
                    "wind_speed_10m": row.get("wind_speed_10m", ""),
                    "wind_gusts_10m": row.get("wind_gusts_10m", ""),
                    **flags,
                    "precip_grade": grade,
                    "precip_quantile_grade": q_grade,
                    "is_normal_weather": int(normal),
                }
                writer.writerow(output_row)
                rows_written += 1

    # Audit summary
    print(f"[AUDIT] output={output_csv}")
    print(f"[AUDIT] rows={rows_written}")
    for k, v in sorted(flag_counts.items()):
        print(f"[AUDIT] {k}={v}")
    # Re-count normal from flags
    print("[AUDIT] precip_grade distribution: see output CSV for details")
    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(RAW_WEATHER_HOURLY_CSV),
        help="Open-Meteo hourly CSV.",
    )
    parser.add_argument(
        "--output",
        default=str(STAGING_WEATHER_HOURLY_LABELED),
        help="Labeled hourly weather CSV.",
    )
    args = parser.parse_args()

    rows = build_labels(Path(args.input), Path(args.output))
    print(f"[AUDIT] total_rows={rows}")


if __name__ == "__main__":
    main()
