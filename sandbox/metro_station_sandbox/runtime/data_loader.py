from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .audit import audit_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ods.ods_reader import ODS  # noqa: E402


@dataclass(frozen=True)
class StationHourProfile:
    station_name: str
    hour: int
    entry_count_hour: int
    exit_count_hour: int
    source_label: str
    sample_hours: int


def _normal_workday_mask(df: pd.DataFrame) -> pd.Series:
    return (
        (df["is_normal_weather"].astype(int) == 1)
        & (df["is_holiday"].astype(int) == 0)
        & (df["is_makeup_workday"].astype(int) == 0)
    )


def _station_mask(df: pd.DataFrame, station_name: str) -> pd.Series:
    exact = df["station_name"].astype(str) == station_name
    display = df.get("display_name", pd.Series("", index=df.index)).astype(str) == station_name
    return exact | display


def load_station_hour_profile(
    station_name: str = "小寨",
    hour: int = 18,
    *,
    normal_workday: bool = True,
    audit_enabled: bool = True,
) -> StationHourProfile:
    """Load a station-hour profile from the registered ADS reader."""

    df = ODS.station_panel()
    df.columns = df.columns.str.strip()
    df["hour"] = df["hour"].astype(int)

    mask = _station_mask(df, station_name) & (df["hour"] == int(hour))
    if normal_workday:
        mask = mask & _normal_workday_mask(df)

    selected = df.loc[mask].copy()
    source_label = "normal_workday_mean"

    if selected.empty and normal_workday:
        all_days_mask = _station_mask(df, station_name) & (df["hour"] == int(hour))
        selected = df.loc[all_days_mask].copy()
        source_label = "all_days_mean"
        if audit_enabled:
            audit_event(
                "station_hour_profile_all_days_substitute",
                source="data_loader",
                severity="warning",
                context={
                    "station_name": station_name,
                    "hour": int(hour),
                    "reason": "normal_workday_selection_empty",
                    "sample_hours": int(len(selected)),
                },
            )

    if selected.empty:
        station_names = sorted(df["station_name"].astype(str).unique())[:30]
        preview = ", ".join(station_names)
        raise ValueError(f"station/hour not found: {station_name} hour={hour}. Examples: {preview}")

    entry = int(round(float(selected["entry_count"].astype(float).mean())))
    exit_ = int(round(float(selected["exit_count"].astype(float).mean())))
    canonical_name = str(selected["station_name"].iloc[0])

    return StationHourProfile(
        station_name=canonical_name,
        hour=int(hour),
        entry_count_hour=max(0, entry),
        exit_count_hour=max(0, exit_),
        source_label=source_label,
        sample_hours=int(len(selected)),
    )
