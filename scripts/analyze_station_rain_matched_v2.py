"""Enhanced station-level rain matched comparison (v2).

Upgrades over v1:
  - Calendar exclusion: holidays and makeup workdays excluded from candidates
  - Three-tier fallback: ±21d/5°C → ±35d/5°C → ±35d/8°C
  - Temperature window matching
  - is_normal_weather flag from weather v2 (replaces old weather_intensity check)
  - Quantile precipitation grouping for rain rows
  - Reports match_tier and matched_n for every observation
  - Distance-weighted baseline (triangular kernel on date distance)
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median


# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.ods.ods_reader import ODS  # noqa: E402


METRICS = ["entry_count", "exit_count", "total_count"]


def parse_date(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def time_group(hour: int) -> str:
    if 7 <= hour <= 9:
        return "morning_peak"
    if 17 <= hour <= 19:
        return "evening_peak"
    if 10 <= hour <= 16:
        return "daytime_offpeak"
    if 20 <= hour <= 23:
        return "evening_offpeak"
    return "night"


def mean_safe(values: list[float]) -> float:
    if not values:
        return math.nan
    return sum(values) / len(values)


# ─────────────────────────────────────────────
# Read panel (ADS by default)
# ─────────────────────────────────────────────
def _int_safe(value: object, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def _float_safe(value: object, default: float = math.nan) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def iter_panel_rows(
    input_path: Path | None,
) -> tuple[dict[tuple[str, int, int], list[dict[str, object]]], list[dict[str, object]], int]:
    """Build candidate index + rain rows from ADS (default) or legacy CSV.

    Returns (candidate_index, rain_rows, total_rows).
    """
    index: dict[tuple[str, int, int], list[dict[str, object]]] = defaultdict(list)
    rain_rows: list[dict[str, object]] = []
    total_rows = 0

    def _consume_record(rec: dict[str, object]) -> None:
        nonlocal total_rows
        total_rows += 1

        station_name = str(rec.get("station_name", "")).strip()
        if not station_name:
            return

        date_raw = rec.get("date")
        if isinstance(date_raw, date):
            date_obj = date_raw
            date_str = date_obj.isoformat()
        else:
            date_str = str(date_raw).strip()
            if not date_str:
                return
            date_obj = parse_date(date_str)

        hour_int = _int_safe(rec.get("hour"))
        weekday = date_obj.weekday()

        out: dict[str, object] = {
            "date": date_str,
            "hour": hour_int,
            "date_obj": date_obj,
            "weekday": weekday,
            "hour_int": hour_int,
            "time_group": time_group(hour_int),
            "station_name": station_name,
            "entry_count": _float_safe(rec.get("entry_count"), 0.0),
            "exit_count": _float_safe(rec.get("exit_count"), 0.0),
            "total_count": _float_safe(rec.get("total_count"), 0.0),
            "temperature_2m": rec.get("temperature_2m", ""),
            "precipitation": rec.get("precipitation", ""),
            "precip_quantile_grade": rec.get("precip_quantile_grade", ""),
            "rain_flag": _int_safe(rec.get("rain_flag")),
            "is_normal_weather": _int_safe(rec.get("is_normal_weather")),
            "is_holiday": _int_safe(rec.get("is_holiday")),
            "is_makeup_workday": _int_safe(rec.get("is_makeup_workday")),
        }
        out["_temp"] = _float_safe(rec.get("temperature_2m"))
        out["_precip"] = _float_safe(rec.get("precipitation"), 0.0)

        key = (station_name, hour_int, weekday)

        if (
            int(out["is_normal_weather"]) == 1
            and int(out["is_holiday"]) == 0
            and int(out["is_makeup_workday"]) == 0
        ):
            index[key].append(out)

        if (
            int(out["rain_flag"]) == 1
            and int(out["is_holiday"]) == 0
            and int(out["is_makeup_workday"]) == 0
        ):
            rain_rows.append(out)

    if input_path is None:
        df = ODS.station_panel()
        df.columns = df.columns.str.strip()
        cols = list(df.columns)
        col_idx = {c: i for i, c in enumerate(cols)}
        required = [
            "date",
            "hour",
            "station_name",
            "entry_count",
            "exit_count",
            "total_count",
            "temperature_2m",
            "precipitation",
            "precip_quantile_grade",
            "rain_flag",
            "is_normal_weather",
            "is_holiday",
            "is_makeup_workday",
        ]
        missing = [c for c in required if c not in col_idx]
        if missing:
            raise SystemExit(f"[AUDIT][FATAL] ADS station panel missing columns: {missing}")

        for tup in df.itertuples(index=False, name=None):
            rec = {c: tup[col_idx[c]] for c in required}
            _consume_record(rec)
    else:
        if not input_path.exists():
            raise SystemExit(f"[AUDIT][FATAL] missing input: {input_path}")
        print(f"[AUDIT][WARN] Using legacy CSV input (preferred: ADS via ODS): {input_path}")
        with input_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row = {k.strip(): v for k, v in row.items()}
                _consume_record(row)

    for candidates in index.values():
        candidates.sort(key=lambda r: r["date_obj"])

    return index, rain_rows, total_rows


# ─────────────────────────────────────────────
# Candidate index: normal weather + exclude holidays
# ─────────────────────────────────────────────
def build_candidate_index(
    rows: list[dict[str, object]],
) -> dict[tuple[str, int, int], list[dict[str, object]]]:
    """Index: (station, hour, weekday) → sorted list of normal-weather candidates."""
    index: dict[tuple[str, int, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        # Use v2 is_normal_weather flag
        if row.get("is_normal_weather") != "1":
            continue
        # Exclude holidays and makeup workdays from candidates
        if row.get("is_holiday") == "1" or row.get("is_makeup_workday") == "1":
            continue
        key = (row["station_name"], int(row["hour_int"]), int(row["weekday"]))
        index[key].append(row)

    for candidates in index.values():
        candidates.sort(key=lambda r: r["date_obj"])
    return index


# ─────────────────────────────────────────────
# Three-tier fallback matching with temperature window
# ─────────────────────────────────────────────
MATCH_TIERS = [
    {"label": "tier1", "window_days": 21, "temp_tol": 5.0},
    {"label": "tier2", "window_days": 35, "temp_tol": 5.0},
    {"label": "tier3", "window_days": 35, "temp_tol": 8.0},
]


def triangular_weight(distance_days: int, window_days: int) -> float:
    """Triangular kernel: weight = 1 - |d|/(W+1), so boundary gets small positive weight."""
    if window_days <= 0:
        return 1.0
    # Use (window_days + 1) so that dist == window_days still gets positive weight
    w = 1.0 - abs(distance_days) / (window_days + 1)
    return max(w, 0.0)


def matched_baseline(
    rain_row: dict[str, object],
    candidates: list[dict[str, object]],
    metric: str,
) -> tuple[float | None, int, str]:
    """Three-tier fallback matching with distance-weighted average.

    Returns (baseline_value, matched_n, match_tier).
    """
    rain_date = rain_row["date_obj"]
    rain_temp = rain_row["_temp"]

    for tier in MATCH_TIERS:
        window = tier["window_days"]
        temp_tol = tier["temp_tol"]

        matched = []
        for c in candidates:
            if c["date_obj"] == rain_date:
                continue
            day_dist = abs((c["date_obj"] - rain_date).days)
            if day_dist > window:
                continue
            # Temperature window check (skip if either temp is NaN)
            c_temp = c["_temp"]
            if not (math.isnan(rain_temp) or math.isnan(c_temp)):
                if abs(rain_temp - c_temp) > temp_tol:
                    continue
            matched.append((c, day_dist))

        if matched:
            # Distance-weighted average (triangular kernel)
            total_weight = 0.0
            weighted_sum = 0.0
            for c, dist in matched:
                w = triangular_weight(dist, window)
                assert w > 0, f"Zero weight: dist={dist}, window={window}"
                weighted_sum += w * float(c[metric])
                total_weight += w
            # 规则 14: 除法前检查分母非零
            assert total_weight > 0, "Total weight is zero"
            baseline = weighted_sum / total_weight
            return baseline, len(matched), tier["label"]

    return None, 0, "unmatched"


# ─────────────────────────────────────────────
# Summary aggregation
# ─────────────────────────────────────────────
def summarize_group(records: list[dict[str, object]]) -> dict[str, object]:
    rain_vals = [float(r["rain_value"]) for r in records]
    base_vals = [float(r["baseline_value"]) for r in records]
    deltas = [float(r["delta"]) for r in records]
    pct_deltas = [float(r["delta_pct"]) for r in records]
    matched_ns = [float(r["matched_n"]) for r in records]

    base_mean = mean_safe(base_vals)
    delta_mean = mean_safe(deltas)

    tier_counts = defaultdict(int)
    for r in records:
        tier_counts[r["match_tier"]] += 1

    result: dict[str, object] = {
        "observations": len(records),
        "rain_hours": len(set((r["date"], r["hour"]) for r in records)),
        "mean_rain_value": round(mean_safe(rain_vals), 2),
        "mean_baseline": round(base_mean, 2),
        "mean_delta": round(delta_mean, 2),
        "median_delta": round(median(deltas), 2),
        "mean_delta_pct": round(delta_mean / base_mean, 6) if base_mean != 0 else math.nan,
        "median_delta_pct": round(median(pct_deltas), 6),
        "mean_matched_n": round(mean_safe(matched_ns), 1),
    }
    for tier_info in MATCH_TIERS:
        label = tier_info["label"]
        result[f"{label}_share"] = (
            round(tier_counts.get(label, 0) / len(records), 4) if records else 0.0
        )
    return result


# ─────────────────────────────────────────────
# Main analysis
# ─────────────────────────────────────────────
def analyze(input_path: Path | None, output_detail: Path, output_summary: Path) -> None:
    panel_path = input_path
    if panel_path is None:
        print("[AUDIT] Loading panel: ADS (ODS.station_panel)")
    else:
        print(f"[AUDIT] Loading panel: {panel_path}")

    index, rain_rows, total_rows = iter_panel_rows(panel_path)
    print(f"[AUDIT] total_rows={total_rows}")
    print(f"[AUDIT] candidate_keys={len(index)}")
    print(f"[AUDIT] rain_rows (excl holidays)={len(rain_rows)}")

    # ─── Detail records ───
    details: list[dict[str, object]] = []
    unmatched = 0
    for row in rain_rows:
        key = (row["station_name"], int(row["hour_int"]), int(row["weekday"]))
        candidates = index.get(key, [])
        for metric in METRICS:
            baseline, matched_n, match_tier = matched_baseline(row, candidates, metric)
            if baseline is None:
                unmatched += 1
                continue
            # 规则 14
            if baseline == 0:
                continue
            rain_value = float(row[metric])
            delta = rain_value - baseline
            details.append(
                {
                    "date": row["date"],
                    "hour": row["hour"],
                    "weekday": row["weekday"],
                    "time_group": row["time_group"],
                    "station_name": row["station_name"],
                    "metric": metric,
                    "rain_value": round(rain_value, 2),
                    "baseline_value": round(baseline, 2),
                    "delta": round(delta, 2),
                    "delta_pct": round(delta / baseline, 6),
                    "matched_n": matched_n,
                    "match_tier": match_tier,
                    "precipitation": row.get("precipitation", ""),
                    "precip_quantile_grade": row.get("precip_quantile_grade", ""),
                    "temperature_2m": row.get("temperature_2m", ""),
                }
            )

    print(f"[AUDIT] detail_rows={len(details)} unmatched={unmatched}")

    # ─── Write detail CSV ───
    output_detail.parent.mkdir(parents=True, exist_ok=True)
    detail_fields = [
        "date",
        "hour",
        "weekday",
        "time_group",
        "station_name",
        "metric",
        "rain_value",
        "baseline_value",
        "delta",
        "delta_pct",
        "matched_n",
        "match_tier",
        "precipitation",
        "precip_quantile_grade",
        "temperature_2m",
    ]
    with output_detail.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(details)

    # ─── Summary: by station × metric, and by time_group × metric ───
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for d in details:
        grouped[("station", d["station_name"], d["metric"])].append(d)
        grouped[("time_group", d["time_group"], d["metric"])].append(d)
        grouped[("overall", "all", d["metric"])].append(d)
        # Also group by quantile grade
        q_grade = d.get("precip_quantile_grade", "")
        if q_grade:
            grouped[("quantile", q_grade, d["metric"])].append(d)

    summary_rows = []
    for (group_type, group_value, metric), records in sorted(grouped.items()):
        row: dict[str, object] = {
            "group_type": group_type,
            "group_value": group_value,
            "metric": metric,
        }
        row.update(summarize_group(records))
        summary_rows.append(row)

    output_summary.parent.mkdir(parents=True, exist_ok=True)
    summary_fields = [
        "group_type",
        "group_value",
        "metric",
        "observations",
        "rain_hours",
        "mean_rain_value",
        "mean_baseline",
        "mean_delta",
        "median_delta",
        "mean_delta_pct",
        "median_delta_pct",
        "mean_matched_n",
        "tier1_share",
        "tier2_share",
        "tier3_share",
    ]
    with output_summary.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"[AUDIT] output_detail={output_detail}")
    print(f"[AUDIT] output_summary={output_summary}")
    print(f"[AUDIT] summary_rows={len(summary_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="",
        help="Legacy CSV panel path. Leave empty to use ADS via ODS.",
    )
    parser.add_argument(
        "--output-detail",
        default="data/analysis/station_rain_matched_detail_v2_2025H1.csv",
    )
    parser.add_argument(
        "--output-summary",
        default="data/analysis/station_rain_matched_summary_v2_2025H1.csv",
    )
    args = parser.parse_args()

    analyze(
        Path(args.input) if args.input else None,
        Path(args.output_detail),
        Path(args.output_summary),
    )


if __name__ == "__main__":
    main()
