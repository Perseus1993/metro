"""Stage 1: Baseline characterization under normal weather.

Produces descriptive statistics for RQ1:
  - Station load classification (daily mean ridership)
  - Peak-to-offpeak ratio (morning peak / daytime offpeak)
  - Entry/exit ratio per station
  - Transfer station and high-load hub identification
  - Section-level baseline load ranking
  - Hourly network profile
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metro_data_warehouse.ods.reader import ODS  # noqa: E402

SEED = 42
np.random.seed(SEED)

OUTPUT_DIR = Path("data/analysis/baseline")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────
def load_station_panel() -> pd.DataFrame:
    df = ODS.station_panel()
    df.columns = df.columns.str.strip()
    return df


def load_section_panel() -> pd.DataFrame:
    df = ODS.section_panel()
    df.columns = df.columns.str.strip()
    return df


def load_station_master(path: Path) -> pd.DataFrame:
    # Keep signature for backward compatibility, but prefer ODS dim_station.
    df = ODS.dim_station()
    df.columns = df.columns.str.strip()
    if "station_name" in df.columns and "name" not in df.columns:
        df = df.rename(columns={"station_name": "name"})
    return df


def load_poi_summary(path: Path) -> pd.DataFrame:
    print(f"[AUDIT] Loading POI summary: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    return df


# ─────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────
def filter_normal_weather(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only normal weather, non-holiday, non-makeup workdays."""
    mask = (
        (df["is_normal_weather"].astype(int) == 1)
        & (df["is_holiday"].astype(int) == 0)
        & (df["is_makeup_workday"].astype(int) == 0)
    )
    out = df.loc[mask].copy()
    print(
        f"[AUDIT] filter_normal_weather: {len(df)} -> {len(out)} ({len(out) / len(df) * 100:.1f}%)"
    )
    return out


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


# ─────────────────────────────────────────────
# Station baseline metrics
# ─────────────────────────────────────────────
def station_baseline_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-station baseline metrics under normal weather."""
    df = df.copy()
    df["total_count"] = df["entry_count"].astype(float) + df["exit_count"].astype(float)
    df["hour"] = df["hour"].astype(int)
    df["time_group"] = df["hour"].apply(time_group)

    # Daily station totals
    daily = (
        df.groupby(["station_name", "date"])
        .agg(
            daily_entry=("entry_count", "sum"),
            daily_exit=("exit_count", "sum"),
            daily_total=("total_count", "sum"),
        )
        .reset_index()
    )

    # Station-level daily averages
    station_daily = (
        daily.groupby("station_name")
        .agg(
            mean_daily_entry=("daily_entry", "mean"),
            mean_daily_exit=("daily_exit", "mean"),
            mean_daily_total=("daily_total", "mean"),
            std_daily_total=("daily_total", "std"),
            normal_days=("date", "nunique"),
        )
        .reset_index()
    )

    # 规则 14: check before division
    station_daily["cv_daily"] = np.where(
        station_daily["mean_daily_total"] > 0,
        station_daily["std_daily_total"] / station_daily["mean_daily_total"],
        np.nan,
    )
    station_daily["entry_exit_ratio"] = np.where(
        station_daily["mean_daily_exit"] > 0,
        station_daily["mean_daily_entry"] / station_daily["mean_daily_exit"],
        np.nan,
    )

    # Peak hourly means per station
    peak_hourly = (
        df.groupby(["station_name", "time_group"])
        .agg(
            mean_hourly=("total_count", "mean"),
        )
        .reset_index()
    )
    peak_pivot = peak_hourly.pivot(
        index="station_name", columns="time_group", values="mean_hourly"
    ).reset_index()
    peak_pivot.columns.name = None

    # Peak ratio
    if "morning_peak" in peak_pivot.columns and "daytime_offpeak" in peak_pivot.columns:
        peak_pivot["morning_peak_ratio"] = np.where(
            peak_pivot["daytime_offpeak"] > 0,
            peak_pivot["morning_peak"] / peak_pivot["daytime_offpeak"],
            np.nan,
        )
    if "evening_peak" in peak_pivot.columns and "daytime_offpeak" in peak_pivot.columns:
        peak_pivot["evening_peak_ratio"] = np.where(
            peak_pivot["daytime_offpeak"] > 0,
            peak_pivot["evening_peak"] / peak_pivot["daytime_offpeak"],
            np.nan,
        )

    # Merge
    result = station_daily.merge(peak_pivot, on="station_name", how="left")

    # Load classification (terciles)
    q33 = result["mean_daily_total"].quantile(0.333)
    q67 = result["mean_daily_total"].quantile(0.667)
    result["load_class"] = pd.cut(
        result["mean_daily_total"],
        bins=[-1, q33, q67, float("inf")],
        labels=["low", "medium", "high"],
    )

    return result.sort_values("mean_daily_total", ascending=False)


# ─────────────────────────────────────────────
# Section baseline metrics
# ─────────────────────────────────────────────
def section_baseline_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Per-section baseline hourly load under normal weather."""
    df = df.copy()
    df["hour"] = df["hour"].astype(int)
    df["time_group"] = df["hour"].apply(time_group)
    df["section_flow_hourly"] = df["section_flow_hourly"].astype(float)

    # Overall section metrics
    section_agg = (
        df.groupby(["line_label", "direction", "section"])
        .agg(
            mean_hourly_flow=("section_flow_hourly", "mean"),
            max_hourly_flow=("section_flow_hourly", "max"),
            std_hourly_flow=("section_flow_hourly", "std"),
            normal_hours=("section_flow_hourly", "count"),
        )
        .reset_index()
    )

    section_agg["cv"] = np.where(
        section_agg["mean_hourly_flow"] > 0,
        section_agg["std_hourly_flow"] / section_agg["mean_hourly_flow"],
        np.nan,
    )

    # Peak-hour section flow
    peak_sec = df[df["time_group"].isin(["morning_peak", "evening_peak"])]
    peak_sec_agg = (
        peak_sec.groupby(["line_label", "direction", "section"])
        .agg(
            mean_peak_flow=("section_flow_hourly", "mean"),
        )
        .reset_index()
    )

    result = section_agg.merge(peak_sec_agg, on=["line_label", "direction", "section"], how="left")
    result["peak_ratio"] = np.where(
        result["mean_hourly_flow"] > 0,
        result["mean_peak_flow"] / result["mean_hourly_flow"],
        np.nan,
    )

    return result.sort_values("mean_hourly_flow", ascending=False)


# ─────────────────────────────────────────────
# Network hourly profile
# ─────────────────────────────────────────────
def network_hourly_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly network-level entry/exit/total profile under normal weather."""
    df = df.copy()
    df["total_count"] = df["entry_count"].astype(float) + df["exit_count"].astype(float)
    df["hour"] = df["hour"].astype(int)

    hourly = (
        df.groupby("hour")
        .agg(
            mean_entry=("entry_count", "mean"),
            mean_exit=("exit_count", "mean"),
            mean_total=("total_count", "mean"),
            std_total=("total_count", "std"),
        )
        .reset_index()
    )

    hourly["cv"] = np.where(
        hourly["mean_total"] > 0,
        hourly["std_total"] / hourly["mean_total"],
        np.nan,
    )

    return hourly


# ─────────────────────────────────────────────
# Transfer station identification
# ─────────────────────────────────────────────
def identify_transfer_stations(master: pd.DataFrame) -> pd.DataFrame:
    """Identify transfer stations (serving multiple lines)."""
    master = master.copy()
    master["n_lines"] = master["line_refs"].apply(
        lambda x: len(str(x).split("|")) if pd.notna(x) and str(x).strip() else 0
    )
    master["is_transfer"] = (master["n_lines"] >= 2).astype(int)
    return master[["name", "display_name", "line_refs", "n_lines", "is_transfer"]]


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main() -> None:
    report_path = OUTPUT_DIR / "baseline_report.txt"
    report_file = open(report_path, "w", encoding="utf-8")

    class Tee:
        def __init__(self, *files):
            self.files = files

        def write(self, data):
            for f in self.files:
                f.write(data)

        def flush(self):
            for f in self.files:
                f.flush()

    old_stdout = sys.stdout
    sys.stdout = Tee(sys.stdout, report_file)

    try:
        # ─── Load data ───
        stn_panel = load_station_panel()
        sec_panel = load_section_panel()
        master = load_station_master(Path("output/xian_metro_station_master.csv"))
        poi = load_poi_summary(Path("output/xian_station_poi_all_summary_600m.csv"))

        # ─── Filter to normal weather ───
        stn_normal = filter_normal_weather(stn_panel)
        sec_normal = filter_normal_weather(sec_panel)

        # ─── 1. Station baseline ───
        print("\n" + "=" * 70)
        print("STATION BASELINE (normal weather, non-holiday)")
        print("=" * 70)
        stn_metrics = station_baseline_metrics(stn_normal)
        stn_metrics.to_csv(
            OUTPUT_DIR / "station_baseline_metrics.csv", index=False, float_format="%.2f"
        )
        print(f"\n[AUDIT] Stations: {len(stn_metrics)}")
        print("[AUDIT] Load class distribution:")
        print(stn_metrics["load_class"].value_counts().to_string())
        print("\n[AUDIT] Top 15 stations by mean daily ridership:")
        top15 = stn_metrics.head(15)[
            [
                "station_name",
                "mean_daily_total",
                "entry_exit_ratio",
                "morning_peak_ratio",
                "evening_peak_ratio",
                "load_class",
            ]
        ]
        print(top15.to_string(index=False))

        print("\n[AUDIT] Bottom 10 stations:")
        bot10 = stn_metrics.tail(10)[["station_name", "mean_daily_total", "cv_daily", "load_class"]]
        print(bot10.to_string(index=False))

        # Summary stats
        print("\n[AUDIT] Entry/exit ratio summary:")
        print(stn_metrics["entry_exit_ratio"].describe().to_string())
        print("\n[AUDIT] Morning peak ratio summary:")
        print(stn_metrics["morning_peak_ratio"].describe().to_string())

        # ─── 2. Transfer stations ───
        print("\n" + "=" * 70)
        print("TRANSFER STATIONS")
        print("=" * 70)
        transfers = identify_transfer_stations(master)
        transfer_list = transfers[transfers["is_transfer"] == 1]
        print(f"[AUDIT] Transfer stations: {len(transfer_list)} / {len(transfers)}")
        print(transfer_list[["name", "line_refs", "n_lines"]].to_string(index=False))

        # Merge transfer flag into station metrics
        stn_metrics = stn_metrics.merge(
            transfers[["name", "n_lines", "is_transfer"]],
            left_on="station_name",
            right_on="name",
            how="left",
        )
        # Transfer vs non-transfer comparison
        transfer_compare = (
            stn_metrics.groupby("is_transfer")
            .agg(
                mean_daily=("mean_daily_total", "mean"),
                median_daily=("mean_daily_total", "median"),
                n=("station_name", "count"),
            )
            .reset_index()
        )
        print("\n[AUDIT] Transfer vs non-transfer daily ridership:")
        print(transfer_compare.to_string(index=False))

        # ─── 3. Section baseline ───
        print("\n" + "=" * 70)
        print("SECTION BASELINE (normal weather)")
        print("=" * 70)
        sec_metrics = section_baseline_metrics(sec_normal)
        sec_metrics.to_csv(
            OUTPUT_DIR / "section_baseline_metrics.csv", index=False, float_format="%.2f"
        )
        print(f"[AUDIT] Sections: {len(sec_metrics)}")
        print("\n[AUDIT] Top 20 sections by mean hourly flow:")
        top20_sec = sec_metrics.head(20)[
            [
                "line_label",
                "direction",
                "section",
                "mean_hourly_flow",
                "max_hourly_flow",
                "peak_ratio",
            ]
        ]
        print(top20_sec.to_string(index=False))

        print("\n[AUDIT] Section flow summary by line:")
        line_summary = (
            sec_metrics.groupby("line_label")
            .agg(
                n_sections=("section", "count"),
                mean_flow=("mean_hourly_flow", "mean"),
                max_flow=("max_hourly_flow", "max"),
            )
            .reset_index()
            .sort_values("mean_flow", ascending=False)
        )
        print(line_summary.to_string(index=False))

        # ─── 4. Network hourly profile ───
        print("\n" + "=" * 70)
        print("NETWORK HOURLY PROFILE (normal weather)")
        print("=" * 70)
        hourly = network_hourly_profile(stn_normal)
        hourly.to_csv(OUTPUT_DIR / "network_hourly_profile.csv", index=False, float_format="%.2f")
        print(hourly.to_string(index=False))

        # ─── 5. POI context summary ───
        print("\n" + "=" * 70)
        print("POI CONTEXT (600m buffer)")
        print("=" * 70)
        print(f"[AUDIT] POI summary: {len(poi)} stations × {len(poi.columns)} columns")
        print(f"[AUDIT] POI columns: {list(poi.columns)}")
        poi_cols = [c for c in poi.columns if c not in ("station", "station_name", "name")]
        if poi_cols:
            print("[AUDIT] POI top-level stats:")
            for c in poi_cols[:10]:
                vals = pd.to_numeric(poi[c], errors="coerce")
                if vals.notna().sum() > 0:
                    print(f"  {c}: mean={vals.mean():.1f} max={vals.max():.0f}")

        print(f"\n[AUDIT] All baseline outputs saved to {OUTPUT_DIR}/")

    finally:
        sys.stdout = old_stdout
        report_file.close()

    print(f"Done. Report at: {report_path}")


if __name__ == "__main__":
    main()
