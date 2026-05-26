"""Controlled weather comparisons for metro network flow and OD panels.

For each metric, the script builds a baseline from normal-weather observations
within the same hour and day type (weekday/weekend), then summarizes the
weather-period deviation from that matched baseline.
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
WEATHER_FLAGS = [
    "rain_flag",
    "moderate_rain_flag",
    "hot_flag",
    "very_hot_flag",
    "freezing_flag",
    "windy_flag",
]


def parse_date(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def day_type(value: str) -> str:
    return "weekend" if parse_date(value).weekday() >= 5 else "weekday"


def read_panel(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["day_type"] = day_type(row["date"])
    return rows


def read_panel_ads(kind: str) -> list[dict[str, str]]:
    if kind == "network":
        df = ODS.network_panel()
    elif kind == "od_network":
        df = ODS.od_network_panel()
    else:
        raise ValueError(f"unknown kind={kind}")

    df.columns = df.columns.str.strip()
    df["date"] = df["date"].astype(str)
    df["hour"] = df["hour"].astype(int)
    if "day_of_week" in df.columns:
        df["day_type"] = (
            df["day_of_week"].astype(int).apply(lambda d: "weekend" if d >= 5 else "weekday")
        )
    else:
        df["day_type"] = df["date"].apply(day_type)

    rows = df.to_dict(orient="records")
    # Ensure string keys for downstream code
    out: list[dict[str, str]] = []
    for r in rows:
        out.append({k: str(v) if not isinstance(v, str) else v for k, v in r.items()})
    return out


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_baselines(
    rows: list[dict[str, str]],
    metrics: list[str],
) -> dict[str, dict[tuple[int, str], float]]:
    grouped = {metric: defaultdict(list) for metric in metrics}
    for row in rows:
        # Baseline: normal weather hours; for ADS panels, is_normal_weather is present.
        if "is_normal_weather" in row:
            if row.get("is_normal_weather") != "1":
                continue
            # Exclude holidays/makeup if calendar is available
            if row.get("is_holiday") == "1" or row.get("is_makeup_workday") == "1":
                continue
        else:
            if row.get("weather_intensity") != "normal":
                continue
        key = (int(row["hour"]), row["day_type"])
        for metric in metrics:
            grouped[metric][key].append(float(row[metric]))

    return {
        metric: {key: mean(values) for key, values in metric_groups.items()}
        for metric, metric_groups in grouped.items()
    }


def summarize_category(
    rows: list[dict[str, str]],
    metrics: list[str],
    baselines: dict[str, dict[tuple[int, str], float]],
    category_type: str,
    category_value: str,
    selector,
) -> list[dict[str, object]]:
    selected = [row for row in rows if selector(row)]
    if not selected:
        return []

    summaries = []
    for metric in metrics:
        values = []
        baseline_values = []
        deltas = []
        pct_deltas = []
        skipped = 0

        for row in selected:
            key = (int(row["hour"]), row["day_type"])
            baseline = baselines[metric].get(key)
            if baseline is None or baseline == 0:
                skipped += 1
                continue
            value = float(row[metric])
            values.append(value)
            baseline_values.append(baseline)
            delta = value - baseline
            deltas.append(delta)
            pct_deltas.append(delta / baseline)

        if not values:
            continue

        summaries.append(
            {
                "category_type": category_type,
                "category_value": category_value,
                "metric": metric,
                "observations": len(values),
                "skipped_no_baseline": skipped,
                "mean_value": round(mean(values), 4),
                "mean_matched_normal_baseline": round(mean(baseline_values), 4),
                "mean_controlled_delta": round(mean(deltas), 4),
                "median_controlled_delta": round(median(deltas), 4),
                "mean_delta_over_mean_baseline": round(
                    mean(deltas) / mean(baseline_values),
                    6,
                ),
                "mean_controlled_delta_pct": round(mean(pct_deltas), 6),
                "median_controlled_delta_pct": round(median(pct_deltas), 6),
            }
        )

    return summaries


def build_summaries(
    rows: list[dict[str, str]],
    metrics: list[str],
) -> list[dict[str, object]]:
    baselines = build_baselines(rows, metrics)
    outputs: list[dict[str, object]] = []

    # ADS-first: summarize by rain quantile grades (if available)
    quant_grades = sorted({row.get("precip_quantile_grade", "") for row in rows})
    for grade in quant_grades:
        if not grade or grade == "no_rain":
            continue
        outputs.extend(
            summarize_category(
                rows,
                metrics,
                baselines,
                "precip_quantile_grade",
                grade,
                lambda row, grade=grade: row.get("precip_quantile_grade") == grade,
            )
        )

    for flag in WEATHER_FLAGS:
        outputs.extend(
            summarize_category(
                rows,
                metrics,
                baselines,
                "weather_flag",
                flag,
                lambda row, flag=flag: row.get(flag) == "1",
            )
        )

    return outputs


def write_summary(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "category_type",
        "category_value",
        "metric",
        "observations",
        "skipped_no_baseline",
        "mean_value",
        "mean_matched_normal_baseline",
        "mean_controlled_delta",
        "median_controlled_delta",
        "mean_delta_over_mean_baseline",
        "mean_controlled_delta_pct",
        "median_controlled_delta_pct",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze_panel(input_path: Path, metrics: list[str], output_path: Path) -> None:
    rows = read_panel(input_path)
    summary = build_summaries(rows, metrics)
    write_summary(summary, output_path)
    print(f"input={input_path}")
    print(f"output={output_path}")
    print(f"rows={len(rows)}")
    print(f"summary_rows={len(summary)}")


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
    parser.add_argument(
        "--network-output",
        default="data/analysis/network_weather_controlled_summary_2025H1.csv",
    )
    parser.add_argument(
        "--od-output",
        default="data/analysis/od_weather_controlled_summary_2025H1.csv",
    )
    args = parser.parse_args()

    if args.network_panel:
        rows_net = read_panel(Path(args.network_panel))
    else:
        rows_net = read_panel_ads("network")
    summary_net = build_summaries(rows_net, NETWORK_METRICS)
    write_summary(summary_net, Path(args.network_output))
    print(f"output={args.network_output} rows={len(rows_net)} summary_rows={len(summary_net)}")

    if args.od_panel:
        rows_od = read_panel(Path(args.od_panel))
    else:
        rows_od = read_panel_ads("od_network")
    summary_od = build_summaries(rows_od, OD_METRICS)
    write_summary(summary_od, Path(args.od_output))
    print(f"output={args.od_output} rows={len(rows_od)} summary_rows={len(summary_od)}")


if __name__ == "__main__":
    main()
