"""Station-level rain matched comparison."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median


# Prefer ADS naming (total_count) over legacy enter_exit_count
METRICS = ["entry_count", "exit_count", "total_count"]

# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metro_data_warehouse.ods.reader import ODS  # noqa: E402


def parse_date(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def read_rows(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["date_obj"] = parse_date(row["date"])
            row["weekday"] = row["date_obj"].weekday()
            row["hour_int"] = int(row["hour"])
            rows.append(row)
    return rows


def read_rows_ads() -> list[dict[str, object]]:
    df = ODS.station_panel()
    df.columns = df.columns.str.strip()
    df["date"] = df["date"].astype(str)
    df["hour"] = df["hour"].astype(int)
    rows = df.to_dict(orient="records")
    for row in rows:
        row["date_obj"] = parse_date(row["date"])
        row["weekday"] = row["date_obj"].weekday()
        row["hour_int"] = int(row["hour"])
    return rows


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_candidate_index(rows: list[dict[str, object]]):
    index = defaultdict(list)
    for row in rows:
        if int(row.get("rain_flag", 0)) != 0:
            continue
        if int(row.get("is_normal_weather", 0)) != 1:
            continue
        if int(row.get("is_holiday", 0)) == 1 or int(row.get("is_makeup_workday", 0)) == 1:
            continue
        key = (row["station_name"], int(row["hour_int"]), int(row["weekday"]))
        index[key].append(row)
    for candidates in index.values():
        candidates.sort(key=lambda item: item["date_obj"])
    return index


def matched_value(
    rain_row: dict[str, object],
    candidates: list[dict[str, object]],
    metric: str,
    window_days: int,
) -> tuple[float | None, int]:
    rain_date = rain_row["date_obj"]
    local = [
        row
        for row in candidates
        if row["date_obj"] != rain_date and abs((row["date_obj"] - rain_date).days) <= window_days
    ]
    if local:
        return mean([float(row[metric]) for row in local]), len(local)
    fallback = [row for row in candidates if row["date_obj"] != rain_date]
    if fallback:
        return mean([float(row[metric]) for row in fallback]), len(fallback)
    return None, 0


def summarize(records: list[dict[str, float]]) -> dict[str, object]:
    rain_values = [record["rain_value"] for record in records]
    baseline_values = [record["baseline_value"] for record in records]
    deltas = [record["delta"] for record in records]
    pct_deltas = [record["delta_pct"] for record in records]
    baseline_mean = mean(baseline_values)
    delta_mean = mean(deltas)
    return {
        "observations": len(records),
        "mean_rain_value": round(mean(rain_values), 4),
        "mean_matched_baseline": round(baseline_mean, 4),
        "mean_delta": round(delta_mean, 4),
        "median_delta": round(median(deltas), 4),
        "mean_delta_over_mean_baseline": round(delta_mean / baseline_mean, 6)
        if baseline_mean
        else "",
        "median_delta_pct": round(median(pct_deltas), 6),
        "mean_match_count": round(mean([record["match_count"] for record in records]), 4),
    }


def analyze(input_path: Path | None, output_path: Path, window_days: int) -> int:
    if input_path is not None:
        print(f"[AUDIT][WARN] Using legacy CSV input (preferred: ADS via ODS): {input_path}")
        rows = read_rows(input_path)
    else:
        rows = read_rows_ads()
    index = build_candidate_index(rows)
    rain_rows = [
        row
        for row in rows
        if int(row.get("rain_flag", 0)) == 1
        and int(row.get("is_holiday", 0)) == 0
        and int(row.get("is_makeup_workday", 0)) == 0
    ]
    grouped = defaultdict(list)

    for row in rain_rows:
        base_key = (row["station_name"], int(row["hour_int"]), int(row["weekday"]))
        candidates = index.get(base_key, [])
        for metric in METRICS:
            baseline, match_count = matched_value(row, candidates, metric, window_days)
            if baseline is None or baseline == 0:
                continue
            rain_value = float(row[metric])
            delta = rain_value - baseline
            grouped[(row["station_name"], metric)].append(
                {
                    "rain_value": rain_value,
                    "baseline_value": baseline,
                    "delta": delta,
                    "delta_pct": delta / baseline,
                    "match_count": match_count,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "station_name",
        "metric",
        "observations",
        "mean_rain_value",
        "mean_matched_baseline",
        "mean_delta",
        "median_delta",
        "mean_delta_over_mean_baseline",
        "median_delta_pct",
        "mean_match_count",
    ]

    summary_rows = []
    for (station_name, metric), records in sorted(grouped.items()):
        summary = {
            "station_name": station_name,
            "metric": metric,
        }
        summary.update(summarize(records))
        summary_rows.append(summary)

    summary_rows.sort(
        key=lambda row: (
            row["metric"],
            float(row["mean_delta_over_mean_baseline"])
            if row["mean_delta_over_mean_baseline"] != ""
            else 0,
        )
    )

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"input={input_path}")
    print(f"output={output_path}")
    print(f"rows={len(rows)}")
    print(f"rain_rows={len(rain_rows)}")
    print(f"summary_rows={len(summary_rows)}")
    return len(summary_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="",
        help="Legacy CSV panel path. Leave empty to use ADS via ODS.",
    )
    parser.add_argument(
        "--output",
        default="data/analysis/station_rain_matched_summary_2025H1.csv",
    )
    parser.add_argument("--window-days", type=int, default=21)
    args = parser.parse_args()

    analyze(Path(args.input) if args.input else None, Path(args.output), args.window_days)


if __name__ == "__main__":
    main()
