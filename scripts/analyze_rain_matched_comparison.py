"""Rain-only matched comparisons for metro network flow and OD.

Each rain hour is matched to non-rain, normal-weather observations with the
same hour and weekday within a local date window. This focuses the comparison
on contemporaneous rain effects and reduces broad seasonal/hourly confounding.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.ods.ods_reader import ODS  # noqa: E402


NETWORK_METRICS = ["entry_count", "exit_count", "enter_exit_count"]
OD_METRICS = ["od_total"]


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


def _read_panel_ads(kind: str) -> list[dict[str, object]]:
    if kind == "network":
        df = ODS.network_panel()
    elif kind == "od_network":
        df = ODS.od_network_panel()
    else:
        raise ValueError(f"unknown kind={kind}")

    df.columns = df.columns.str.strip()
    df["date"] = df["date"].astype(str)
    df["hour"] = df["hour"].astype(int)
    rows = df.to_dict(orient="records")
    for row in rows:
        row["date_obj"] = parse_date(row["date"])
        row["weekday"] = row["date_obj"].weekday()
        row["hour_int"] = int(row["hour"])
        row["time_group"] = time_group(row["hour_int"])
    return rows


def _read_panel_csv(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["date_obj"] = parse_date(row["date"])
            row["weekday"] = row["date_obj"].weekday()
            row["hour_int"] = int(row["hour"])
            row["time_group"] = time_group(row["hour_int"])
            rows.append(row)
    return rows


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_candidate_index(
    rows: list[dict[str, object]],
) -> dict[tuple[int, int], list[dict[str, object]]]:
    index: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if int(row.get("rain_flag", 0)) != 0:
            continue
        if int(row.get("is_normal_weather", 0)) != 1:
            continue
        if int(row.get("is_holiday", 0)) == 1 or int(row.get("is_makeup_workday", 0)) == 1:
            continue
        key = (int(row["hour_int"]), int(row["weekday"]))
        index[key].append(row)

    for candidates in index.values():
        candidates.sort(key=lambda item: item["date_obj"])
    return index


def matched_baseline(
    rain_row: dict[str, object],
    candidates: list[dict[str, object]],
    metric: str,
    window_days: int,
) -> tuple[float | None, int, str]:
    rain_date = rain_row["date_obj"]
    local = [
        row
        for row in candidates
        if row["date_obj"] != rain_date and abs((row["date_obj"] - rain_date).days) <= window_days
    ]
    if local:
        return mean([float(row[metric]) for row in local]), len(local), "local_window"

    fallback = [row for row in candidates if row["date_obj"] != rain_date]
    if fallback:
        return mean([float(row[metric]) for row in fallback]), len(fallback), "full_period"

    return None, 0, "no_match"


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    rain_values = [float(row["rain_value"]) for row in records]
    baseline_values = [float(row["baseline_value"]) for row in records]
    deltas = [float(row["delta"]) for row in records]
    pct_deltas = [float(row["delta_pct"]) for row in records]
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
        "mean_match_count": round(mean([float(row["match_count"]) for row in records]), 4),
        "local_window_share": round(
            sum(1 for row in records if row["match_scope"] == "local_window") / len(records),
            6,
        ),
    }


def analyze(
    kind: str,
    input_path: Path | None,
    metrics: list[str],
    output_detail: Path,
    output_summary: Path,
    window_days: int,
) -> None:
    if input_path is None:
        rows = _read_panel_ads(kind)
    else:
        print(f"[AUDIT][WARN] Using legacy CSV input (preferred: ADS via ODS): {input_path}")
        rows = _read_panel_csv(input_path)
    candidate_index = build_candidate_index(rows)
    rain_rows = [
        row
        for row in rows
        if int(row.get("rain_flag", 0)) == 1
        and int(row.get("is_holiday", 0)) == 0
        and int(row.get("is_makeup_workday", 0)) == 0
    ]

    details: list[dict[str, object]] = []
    for row in rain_rows:
        key = (int(row["hour_int"]), int(row["weekday"]))
        candidates = candidate_index.get(key, [])
        for metric in metrics:
            baseline, match_count, match_scope = matched_baseline(
                row,
                candidates,
                metric,
                window_days,
            )
            if baseline is None or baseline == 0:
                continue
            rain_value = float(row[metric])
            delta = rain_value - baseline
            details.append(
                {
                    "date": row["date"],
                    "hour": row["hour"],
                    "weekday": row["weekday"],
                    "time_group": row["time_group"],
                    "metric": metric,
                    "rain_value": round(rain_value, 4),
                    "baseline_value": round(baseline, 4),
                    "delta": round(delta, 4),
                    "delta_pct": round(delta / baseline, 6),
                    "match_count": match_count,
                    "match_scope": match_scope,
                    "precipitation": row.get("precipitation", ""),
                    "temperature_2m": row.get("temperature_2m", ""),
                }
            )

    output_detail.parent.mkdir(parents=True, exist_ok=True)
    detail_fields = [
        "date",
        "hour",
        "weekday",
        "time_group",
        "metric",
        "rain_value",
        "baseline_value",
        "delta",
        "delta_pct",
        "match_count",
        "match_scope",
        "precipitation",
        "temperature_2m",
    ]
    with output_detail.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(details)

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for detail in details:
        grouped[("overall", detail["metric"])].append(detail)
        grouped[(str(detail["time_group"]), detail["metric"])].append(detail)

    summary_rows = []
    for (group, metric), records in sorted(grouped.items()):
        row = {"group": group, "metric": metric}
        row.update(summarize(records))
        summary_rows.append(row)

    summary_fields = [
        "group",
        "metric",
        "observations",
        "mean_rain_value",
        "mean_matched_baseline",
        "mean_delta",
        "median_delta",
        "mean_delta_over_mean_baseline",
        "median_delta_pct",
        "mean_match_count",
        "local_window_share",
    ]
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    with output_summary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"input={input_path}")
    print(f"detail={output_detail}")
    print(f"summary={output_summary}")
    print(f"rows={len(rows)}")
    print(f"rain_hours={len(rain_rows)}")
    print(f"detail_rows={len(details)}")
    print(f"summary_rows={len(summary_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--network-panel",
        default="",
        help="Legacy CSV network panel. Leave empty to use ADS via ODS.",
    )
    parser.add_argument(
        "--od-panel",
        default="",
        help="Legacy CSV OD network panel. Leave empty to use ADS via ODS.",
    )
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument(
        "--network-detail",
        default="data/analysis/network_rain_matched_detail_2025H1.csv",
    )
    parser.add_argument(
        "--network-summary",
        default="data/analysis/network_rain_matched_summary_2025H1.csv",
    )
    parser.add_argument(
        "--od-detail",
        default="data/analysis/od_rain_matched_detail_2025H1.csv",
    )
    parser.add_argument(
        "--od-summary",
        default="data/analysis/od_rain_matched_summary_2025H1.csv",
    )
    args = parser.parse_args()

    analyze(
        "network",
        Path(args.network_panel) if args.network_panel else None,
        NETWORK_METRICS,
        Path(args.network_detail),
        Path(args.network_summary),
        args.window_days,
    )
    analyze(
        "od_network",
        Path(args.od_panel) if args.od_panel else None,
        OD_METRICS,
        Path(args.od_detail),
        Path(args.od_summary),
        args.window_days,
    )


if __name__ == "__main__":
    main()
