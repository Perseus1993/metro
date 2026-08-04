"""Section-level Fixed Effects panel regression for weather disturbance.

Model: log(1 + Flow_{e,t}) = α_e + γ_{h×dow} + δ_week
       + Σ β_k D_k + θ₁ Temp + θ₂ Wind + ε_{e,t}

where e = (line, direction, section) is the section entity.

Same demeaning approach as station FE, with date-clustered SE.
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

SEED = 42
np.random.seed(SEED)

OUTPUT_DIR = Path("data/analysis/section_fe")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────
def load_section_panel() -> pd.DataFrame:
    df = ODS.section_panel()
    df.columns = df.columns.str.strip()
    print(f"[AUDIT] raw_rows={len(df)}")

    # Derived variables
    df["date"] = df["date"].astype(str)
    df["hour"] = df["hour"].astype(int)
    df["day_of_week"] = df["day_of_week"].astype(int)
    df["section_flow_hourly"] = df["section_flow_hourly"].astype(float)

    # log(1 + Flow)
    df["log_flow"] = np.log1p(df["section_flow_hourly"])

    if "section_id" not in df.columns:
        raise SystemExit("[AUDIT][FATAL] section_id missing from ADS panel")
    df["section_id"] = df["section_id"].astype(str)

    # Section entity label (for reporting)
    if "section" not in df.columns:
        df["section"] = df["from_station"].astype(str) + "-" + df["to_station"].astype(str)
    df["section_entity"] = df["line_label"] + "_" + df["direction"] + "_" + df["section"]

    # Hour × DOW
    df["hour_dow"] = df["hour"].astype(str) + "_" + df["day_of_week"].astype(str)

    # Week
    df["week"] = pd.to_datetime(df["date"]).dt.isocalendar().week.astype(int).values

    # Rain quantile dummies
    df["D_rain_low"] = (df["precip_quantile_grade"] == "rain_low").astype(int)
    df["D_rain_mid"] = (df["precip_quantile_grade"] == "rain_mid").astype(int)
    df["D_rain_high"] = (df["precip_quantile_grade"] == "rain_high").astype(int)
    df["rain_any"] = (df["rain_flag"].astype(int) == 1).astype(int)

    # Other weather
    df["D_hot"] = df["hot_flag"].astype(int)
    df["D_freezing"] = df["freezing_flag"].astype(int)
    df["D_windy"] = df["windy_flag"].astype(int)

    # Controls
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

    n_sections = df["section_id"].nunique()
    print(f"[AUDIT] sections={n_sections} rain_any={df['rain_any'].sum()}")
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
# Demeaning
# ─────────────────────────────────────────────
def demean_twoway(
    df: pd.DataFrame,
    cols: list[str],
    fe1: str,
    fe2: str,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> pd.DataFrame:
    result = df[cols].copy().astype(float)
    for iteration in range(max_iter):
        prev = result.values.copy()
        result = result - result.groupby(df[fe1]).transform("mean")
        result = result - result.groupby(df[fe2]).transform("mean")
        diff = np.abs(result.values - prev).max()
        if diff < tol:
            print(f"[AUDIT] demean converged iter={iteration + 1} diff={diff:.2e}")
            break
    else:
        print(f"[AUDIT] demean NOT converged after {max_iter} iters diff={diff:.2e}")
    return result


# ─────────────────────────────────────────────
# Regression
# ─────────────────────────────────────────────
def run_section_fe(
    df: pd.DataFrame,
    y_col: str,
    treat_cols: list[str],
    control_cols: list[str],
    label: str = "main",
) -> dict:
    week_dummies = pd.get_dummies(df["week"], prefix="week", drop_first=True, dtype=float)
    week_cols = list(week_dummies.columns)
    all_x_cols = treat_cols + control_cols + week_cols
    all_demean_cols = [y_col] + treat_cols + control_cols + week_cols

    df_work = pd.concat([df, week_dummies], axis=1)

    print(f"[AUDIT] [{label}] Demeaning {len(all_demean_cols)} vars ...")
    demeaned = demean_twoway(df_work, all_demean_cols, "section_id", "hour_dow")

    y = demeaned[y_col].values
    X = demeaned[all_x_cols].values

    valid = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    n_invalid = (~valid).sum()
    if n_invalid > 0:
        print(f"[AUDIT] [{label}] Dropping {n_invalid} NaN/Inf rows")
        y = y[valid]
        X = X[valid]
        cluster_values = df_work["date"].values[valid]
    else:
        cluster_values = df_work["date"].values

    n_obs = len(y)
    n_fe = df_work["section_id"].nunique() + df_work["hour_dow"].nunique()

    print(f"[AUDIT] [{label}] n_obs={n_obs} n_fe={n_fe}")

    model = sm.OLS(y, X)
    cluster_ids = pd.Categorical(cluster_values).codes
    results = model.fit(cov_type="cluster", cov_kwds={"groups": cluster_ids})

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
                }
            )

    coef_df = pd.DataFrame(coef_table)
    print(f"\n[AUDIT] [{label}] === Section FE Results ===")
    print(
        f"  N={n_obs}, Sections={df_work['section_id'].nunique()}, Clusters={len(set(cluster_ids))}"
    )
    for _, row in coef_df.iterrows():
        sig = (
            "***"
            if row["p"] < 0.01
            else ("**" if row["p"] < 0.05 else ("*" if row["p"] < 0.1 else ""))
        )
        print(
            f"  {row['variable']:<16} β={row['coef']:>8.5f}  SE={row['se']:>8.5f}  "
            f"t={row['t']:>6.2f}  p={row['p']:.4f} {sig}"
        )

    return {"label": label, "coef_df": coef_df, "n_obs": n_obs}


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main() -> None:
    report_path = OUTPUT_DIR / "section_fe_report.txt"
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
        df = load_section_panel()

        # Exclude holidays
        df_reg = df[(df["is_holiday"] == 0) & (df["is_makeup"] == 0)].copy()
        print(
            f"[AUDIT] Regression sample: {len(df_reg)} rows, "
            f"sections={df_reg['section_id'].nunique()}"
        )

        treat_cols = ["D_rain_low", "D_rain_mid", "D_rain_high", "D_hot", "D_freezing", "D_windy"]
        control_cols = ["temperature", "wind_speed"]

        # ─── Main specification ───
        print("\n" + "=" * 70)
        print("MAIN: log(1 + section_flow) ~ rain quantiles + weather + FE")
        print("=" * 70)
        main_result = run_section_fe(df_reg, "log_flow", treat_cols, control_cols, label="MAIN")

        # ─── Binary rain ───
        print("\n" + "=" * 70)
        print("BINARY RAIN (robustness)")
        print("=" * 70)
        run_section_fe(
            df_reg,
            "log_flow",
            ["rain_any", "D_hot", "D_freezing", "D_windy"],
            control_cols,
            label="binary_rain",
        )

        # ─── High-load sections: top 20% ───
        print("\n" + "=" * 70)
        print("HIGH-LOAD SECTIONS (top 20% by mean flow)")
        print("=" * 70)
        section_means = df_reg.groupby("section_entity")["section_flow_hourly"].mean()
        top20_threshold = section_means.quantile(0.80)
        high_load = section_means[section_means >= top20_threshold].index
        df_high = df_reg[df_reg["section_entity"].isin(high_load)].copy()
        print(f"[AUDIT] High-load sections: {len(high_load)} (threshold={top20_threshold:.0f})")
        run_section_fe(df_high, "log_flow", treat_cols, control_cols, label="high_load_top20pct")

        # ─── Low-load sections: bottom 20% ───
        print("\n" + "=" * 70)
        print("LOW-LOAD SECTIONS (bottom 20% by mean flow)")
        print("=" * 70)
        bot20_threshold = section_means.quantile(0.20)
        low_load = section_means[section_means <= bot20_threshold].index
        df_low = df_reg[df_reg["section_entity"].isin(low_load)].copy()
        print(f"[AUDIT] Low-load sections: {len(low_load)} (threshold={bot20_threshold:.0f})")
        run_section_fe(df_low, "log_flow", treat_cols, control_cols, label="low_load_bot20pct")

        # ─── Peak vs offpeak ───
        print("\n" + "=" * 70)
        print("PEAK vs OFFPEAK")
        print("=" * 70)
        for group_name, time_groups in [
            ("peak", ["morning_peak", "evening_peak"]),
            ("offpeak", ["daytime_offpeak", "evening_offpeak", "night"]),
        ]:
            sub = df_reg[df_reg["time_group"].isin(time_groups)].copy()
            run_section_fe(sub, "log_flow", treat_cols, control_cols, label=f"split_{group_name}")

        # ─── Save main coef table ───
        main_result["coef_df"].to_csv(
            OUTPUT_DIR / "main_coef_table.csv", index=False, float_format="%.6f"
        )

        print(f"\n[AUDIT] All section FE results saved to {OUTPUT_DIR}/")

    finally:
        sys.stdout = old_stdout
        report_file.close()

    print(f"Done. Report at: {report_path}")


if __name__ == "__main__":
    main()
