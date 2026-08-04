"""Station-level Fixed Effects panel regression for rain disturbance.

Model: log(1 + Y_{s,t}) = α_s + γ_{h×dow} + δ_week + Σ β_q D_q + θ₁ Temp + θ₂ Wind + ε

Approach: iterative demeaning (zigzag) for station FE + hour×dow FE,
          then OLS with week dummies on demeaned data.
          Date-clustered standard errors.

Diagnostics requested:
  1. Rain intensity group sample sizes (hours, dates)
  2. rain_high distribution by date × hour
  3. rain_high by entry / exit split
  4. Drop top-5% stations re-estimate
  5. Workday/weekend × peak/offpeak splits
  6. Tier1-only (from matching) check
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metro_data_warehouse.ods.reader import ODS  # noqa: E402

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)

OUTPUT_DIR = Path("data/analysis/fe_regression")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────
def load_panel() -> pd.DataFrame:
    df = ODS.station_panel()
    # 规则 10: strip column names
    df.columns = df.columns.str.strip()
    print(f"[AUDIT] raw_rows={len(df)} columns={list(df.columns)[:10]}...")

    # ─── Derived variables ───
    df["date"] = df["date"].astype(str)
    df["hour"] = df["hour"].astype(int)
    df["day_of_week"] = df["day_of_week"].astype(int)

    # log(1 + Y)
    df["log_total"] = np.log1p(df["total_count"].astype(float))
    df["log_entry"] = np.log1p(df["entry_count"].astype(float))
    df["log_exit"] = np.log1p(df["exit_count"].astype(float))

    # Hour × DOW composite
    df["hour_dow"] = df["hour"].astype(str) + "_" + df["day_of_week"].astype(str)

    # Week number (ISO)
    df["week"] = pd.to_datetime(df["date"]).dt.isocalendar().week.astype(int).values

    # Rain dummies (quantile-based)
    df["rain_any"] = (df["rain_flag"].astype(int) == 1).astype(int)
    df["D_rain_low"] = (df["precip_quantile_grade"] == "rain_low").astype(int)
    df["D_rain_mid"] = (df["precip_quantile_grade"] == "rain_mid").astype(int)
    df["D_rain_high"] = (df["precip_quantile_grade"] == "rain_high").astype(int)

    # Other weather flags
    df["D_hot"] = df["hot_flag"].astype(int)
    df["D_freezing"] = df["freezing_flag"].astype(int)
    df["D_windy"] = df["windy_flag"].astype(int)

    # Continuous controls
    df["temperature"] = pd.to_numeric(df["temperature_2m"], errors="coerce")
    df["wind_speed"] = pd.to_numeric(df["wind_speed_10m"], errors="coerce")
    df["temperature"] = df["temperature"].fillna(df["temperature"].median())
    df["wind_speed"] = df["wind_speed"].fillna(df["wind_speed"].median())

    # Calendar
    df["is_holiday"] = df["is_holiday"].astype(int)
    df["is_makeup"] = df["is_makeup_workday"].astype(int)
    df["is_workday"] = df["calendar_type"].isin(["workday", "makeup_workday"]).astype(int)

    # Time group
    df["time_group"] = df["hour"].apply(_time_group)

    if "station_id" not in df.columns:
        raise SystemExit("[AUDIT][FATAL] station_id missing from ADS panel")
    df["station_id"] = df["station_id"].astype(int)

    print(
        f"[AUDIT] panel_rows={len(df)} stations={df['station_id'].nunique()} "
        f"rain_any={df['rain_any'].sum()} "
        f"D_rain_low={df['D_rain_low'].sum()} "
        f"D_rain_mid={df['D_rain_mid'].sum()} "
        f"D_rain_high={df['D_rain_high'].sum()}"
    )
    return df


def _time_group(hour: int) -> str:
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
# FE demeaning (zigzag for two-way FE)
# ─────────────────────────────────────────────
def demean_twoway(
    df: pd.DataFrame,
    cols: list[str],
    fe1: str,
    fe2: str,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> pd.DataFrame:
    """Iterative demeaning for two-way fixed effects (Gauss-Seidel)."""
    result = df[cols].copy().astype(float)
    for iteration in range(max_iter):
        prev = result.values.copy()
        # Demean by FE1
        group_means = result.groupby(df[fe1]).transform("mean")
        result = result - group_means
        # Demean by FE2
        group_means = result.groupby(df[fe2]).transform("mean")
        result = result - group_means
        # Check convergence
        diff = np.abs(result.values - prev).max()
        if diff < tol:
            print(f"[AUDIT] demean converged at iteration {iteration + 1}, diff={diff:.2e}")
            break
    else:
        print(f"[AUDIT] demean did NOT converge after {max_iter} iters, diff={diff:.2e}")
    return result


# ─────────────────────────────────────────────
# Regression runner
# ─────────────────────────────────────────────
def run_fe_regression(
    df: pd.DataFrame,
    y_col: str,
    treat_cols: list[str],
    control_cols: list[str],
    fe1: str = "station_id",
    fe2: str = "hour_dow",
    cluster_col: str = "date",
    label: str = "main",
) -> dict:
    """Run two-way FE regression with week dummies and date-clustered SE."""
    # Week dummies (included explicitly, not absorbed)
    week_dummies = pd.get_dummies(df["week"], prefix="week", drop_first=True, dtype=float)
    week_cols = list(week_dummies.columns)

    all_x_cols = treat_cols + control_cols + week_cols

    # Add week dummies to df temporarily
    df_work = pd.concat([df, week_dummies], axis=1)

    all_demean_cols = [y_col] + treat_cols + control_cols + week_cols

    # Demean by station + hour_dow
    print(f"[AUDIT] [{label}] Demeaning {len(all_demean_cols)} vars by {fe1} + {fe2} ...")
    demeaned = demean_twoway(df_work, all_demean_cols, fe1, fe2)

    y = demeaned[y_col].values
    X = demeaned[all_x_cols].values

    # Check for NaN/Inf
    valid = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    n_invalid = (~valid).sum()
    if n_invalid > 0:
        print(f"[AUDIT] [{label}] Dropping {n_invalid} rows with NaN/Inf")
        y = y[valid]
        X = X[valid]
        cluster_values = df_work[cluster_col].values[valid]
    else:
        cluster_values = df_work[cluster_col].values

    n_obs = len(y)
    n_fe = df_work[fe1].nunique() + df_work[fe2].nunique()
    n_params = X.shape[1]

    print(f"[AUDIT] [{label}] n_obs={n_obs} n_fe_absorbed={n_fe} n_params={n_params}")

    # OLS on demeaned data
    model = sm.OLS(y, X)

    # Date-clustered SE
    cluster_ids = pd.Categorical(cluster_values).codes
    results = model.fit(
        cov_type="cluster",
        cov_kwds={"groups": cluster_ids},
    )

    # Adjust DOF for absorbed FE
    results.df_resid = n_obs - n_fe - n_params

    # Extract treatment coefficients
    coef_table = []
    for i, col_name in enumerate(all_x_cols):
        if col_name in treat_cols or col_name in control_cols:
            coef_table.append(
                {
                    "variable": col_name,
                    "coef": results.params[i],
                    "se": results.bse[i],
                    "t": results.tvalues[i],
                    "p": results.pvalues[i],
                    "ci_lo": results.params[i] - 1.96 * results.bse[i],
                    "ci_hi": results.params[i] + 1.96 * results.bse[i],
                }
            )

    coef_df = pd.DataFrame(coef_table)
    print(f"\n[AUDIT] [{label}] === Regression Results ===")
    print(f"  N={n_obs}, FE absorbed={n_fe}, Clusters (dates)={len(set(cluster_ids))}")
    for _, row in coef_df.iterrows():
        sig = ""
        if row["p"] < 0.01:
            sig = "***"
        elif row["p"] < 0.05:
            sig = "**"
        elif row["p"] < 0.1:
            sig = "*"
        print(
            f"  {row['variable']:<16} β={row['coef']:>8.5f}  SE={row['se']:>8.5f}  "
            f"t={row['t']:>6.2f}  p={row['p']:.4f} {sig}"
        )

    return {
        "label": label,
        "n_obs": n_obs,
        "n_fe": n_fe,
        "n_clusters": len(set(cluster_ids)),
        "coef_df": coef_df,
        "r2_within": 1 - np.var(results.resid) / np.var(y),
        "results": results,
    }


# ─────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────
def diagnostic_sample_sizes(df: pd.DataFrame) -> pd.DataFrame:
    """Diag 1: rain intensity group sample sizes."""
    groups = []
    for grade in ["no_rain", "rain_low", "rain_mid", "rain_high"]:
        sub = df[df["precip_quantile_grade"] == grade]
        groups.append(
            {
                "grade": grade,
                "station_hours": len(sub),
                "unique_hours": sub[["date", "hour"]].drop_duplicates().shape[0],
                "unique_dates": sub["date"].nunique(),
                "unique_stations": sub["station_name"].nunique(),
            }
        )
    result = pd.DataFrame(groups)
    print("\n[AUDIT] === Diag 1: Sample Sizes by Rain Grade ===")
    print(result.to_string(index=False))
    return result


def diagnostic_rain_high_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Diag 2: rain_high distribution by date × hour."""
    rh = df[df["D_rain_high"] == 1]
    dist = (
        rh.groupby(["date", "hour"])
        .agg(
            stations=("station_name", "nunique"),
            mean_precip=("precipitation", lambda x: round(float(x.astype(float).mean()), 2)),
        )
        .reset_index()
    )
    print(f"\n[AUDIT] === Diag 2: rain_high Distribution ({len(dist)} date-hours) ===")
    print(dist.to_string(index=False))
    dist.to_csv(OUTPUT_DIR / "diag2_rain_high_distribution.csv", index=False)
    return dist


def diagnostic_entry_exit_split(
    df: pd.DataFrame,
    treat_cols: list[str],
    control_cols: list[str],
) -> None:
    """Diag 3: rain_high by entry / exit split."""
    for y_col, label in [("log_entry", "entry_only"), ("log_exit", "exit_only")]:
        run_fe_regression(df, y_col, treat_cols, control_cols, label=label)


def diagnostic_drop_top_stations(
    df: pd.DataFrame,
    treat_cols: list[str],
    control_cols: list[str],
    pct: float = 0.95,
) -> None:
    """Diag 4: drop top-5% high-volume stations."""
    station_vol = df.groupby("station_name")["total_count"].mean()
    threshold = station_vol.quantile(pct)
    big_stations = station_vol[station_vol > threshold].index
    print(f"\n[AUDIT] Diag 4: Dropping {len(big_stations)} stations with mean > {threshold:.0f}")
    df_small = df[~df["station_name"].isin(big_stations)].copy()
    # Re-encode station_id
    df_small["station_id"] = pd.Categorical(df_small["station_name"]).codes
    run_fe_regression(
        df_small, "log_total", treat_cols, control_cols, label="drop_top5pct_stations"
    )


def diagnostic_subgroup_splits(
    df: pd.DataFrame,
    treat_cols: list[str],
    control_cols: list[str],
) -> None:
    """Diag 5: workday/weekend × peak/offpeak splits."""
    splits = {
        "workday": df[df["is_workday"] == 1],
        "weekend": df[df["is_workday"] == 0],
        "peak": df[df["time_group"].isin(["morning_peak", "evening_peak"])],
        "offpeak": df[~df["time_group"].isin(["morning_peak", "evening_peak"])],
        "workday_peak": df[
            (df["is_workday"] == 1) & df["time_group"].isin(["morning_peak", "evening_peak"])
        ],
        "weekend_offpeak": df[
            (df["is_workday"] == 0) & ~df["time_group"].isin(["morning_peak", "evening_peak"])
        ],
    }
    for split_name, sub_df in splits.items():
        if len(sub_df) < 1000:
            print(f"[AUDIT] Skipping split '{split_name}': only {len(sub_df)} rows")
            continue
        sub_df = sub_df.copy()
        sub_df["station_id"] = pd.Categorical(sub_df["station_name"]).codes
        run_fe_regression(
            sub_df, "log_total", treat_cols, control_cols, label=f"split_{split_name}"
        )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main() -> None:
    # Redirect print to both stdout and file
    report_path = OUTPUT_DIR / "fe_regression_report.txt"

    class Tee:
        def __init__(self, *files):
            self.files = files

        def write(self, data):
            for f in self.files:
                f.write(data)

        def flush(self):
            for f in self.files:
                f.flush()

    report_file = open(report_path, "w", encoding="utf-8")
    old_stdout = sys.stdout
    sys.stdout = Tee(sys.stdout, report_file)

    try:
        df = load_panel()

        # Exclude holidays from regression sample
        df_reg = df[(df["is_holiday"] == 0) & (df["is_makeup"] == 0)].copy()
        print(f"[AUDIT] Regression sample (excl holidays): {len(df_reg)} rows")

        treat_cols = ["D_rain_low", "D_rain_mid", "D_rain_high", "D_hot", "D_freezing", "D_windy"]
        control_cols = ["temperature", "wind_speed"]

        # ─── Diag 1: Sample sizes ───
        diagnostic_sample_sizes(df_reg)

        # ─── Diag 2: rain_high distribution ───
        diagnostic_rain_high_distribution(df_reg)

        # ─── Main regression ───
        print("\n" + "=" * 70)
        print("MAIN SPECIFICATION: log(1+total_count)")
        print("=" * 70)
        main_result = run_fe_regression(df_reg, "log_total", treat_cols, control_cols, label="MAIN")

        # Also run binary rain model
        print("\n" + "=" * 70)
        print("BINARY RAIN: rain_any (robustness)")
        print("=" * 70)
        treat_binary = ["rain_any", "D_hot", "D_freezing", "D_windy"]
        run_fe_regression(df_reg, "log_total", treat_binary, control_cols, label="binary_rain")

        # ─── Diag 3: entry / exit split ───
        print("\n" + "=" * 70)
        print("DIAG 3: ENTRY / EXIT SPLIT")
        print("=" * 70)
        diagnostic_entry_exit_split(df_reg, treat_cols, control_cols)

        # ─── Diag 4: drop top 5% stations ───
        print("\n" + "=" * 70)
        print("DIAG 4: DROP TOP-5% STATIONS")
        print("=" * 70)
        diagnostic_drop_top_stations(df_reg, treat_cols, control_cols)

        # ─── Diag 5: subgroup splits ───
        print("\n" + "=" * 70)
        print("DIAG 5: SUBGROUP SPLITS")
        print("=" * 70)
        diagnostic_subgroup_splits(df_reg, treat_cols, control_cols)

        # ─── Save main results table ───
        main_result["coef_df"].to_csv(
            OUTPUT_DIR / "main_coef_table.csv", index=False, float_format="%.6f"
        )

        print(f"\n[AUDIT] All results saved to {OUTPUT_DIR}/")
        print(f"[AUDIT] Report: {report_path}")

    finally:
        sys.stdout = old_stdout
        report_file.close()

    print(f"Done. Report at: {report_path}")


if __name__ == "__main__":
    main()
