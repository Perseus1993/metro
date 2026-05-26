"""Build dim_calendar.parquet — 日历维表。

复用 scripts/etl/build_calendar_labels.py 的逻辑，输出 Parquet。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd


# ─────────────────────────────────────────────
# 法定节假日与调休日（硬编码来源已核实: 国务院办公厅2025年节假日安排）
# ─────────────────────────────────────────────
HOLIDAYS: list[tuple[date, date, str]] = [
    (date(2025, 1, 1), date(2025, 1, 1), "元旦"),
    (date(2025, 1, 28), date(2025, 2, 4), "春节"),
    (date(2025, 4, 4), date(2025, 4, 6), "清明节"),
    (date(2025, 5, 1), date(2025, 5, 5), "劳动节"),
    (date(2025, 5, 31), date(2025, 6, 2), "端午节"),
]

MAKEUP_WORKDAYS: list[tuple[date, str]] = [
    (date(2025, 1, 26), "春节补班"),
    (date(2025, 2, 8), "春节补班"),
    (date(2025, 4, 27), "劳动节补班"),
]

SCHOOL_BREAK_START = date(2025, 1, 15)
SCHOOL_BREAK_END = date(2025, 2, 28)

START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 6, 30)

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build(
    output_path: str | Path = "data/ods/dim_calendar.parquet",
) -> pd.DataFrame:
    output_path = Path(output_path)

    # Build holiday map
    holiday_map: dict[date, str] = {}
    for start, end, name in HOLIDAYS:
        d = start
        while d <= end:
            holiday_map[d] = name
            d += timedelta(days=1)

    makeup_map = {d: name for d, name in MAKEUP_WORKDAYS}

    records = []
    d = START_DATE
    while d <= END_DATE:
        dow = d.weekday()
        is_holiday = d in holiday_map
        is_makeup = d in makeup_map

        if is_holiday:
            cal_type = "holiday"
            cal_name = holiday_map[d]
        elif is_makeup:
            cal_type = "makeup_workday"
            cal_name = makeup_map[d]
        elif dow >= 5:
            cal_type = "weekend"
            cal_name = ""
        else:
            cal_type = "workday"
            cal_name = ""

        records.append(
            {
                "date": d,
                "day_of_week": dow,
                "dow_name": DOW_NAMES[dow],
                "is_holiday": int(is_holiday),
                "is_makeup_workday": int(is_makeup),
                "is_school_break": int(SCHOOL_BREAK_START <= d <= SCHOOL_BREAK_END),
                "calendar_type": cal_type,
                "calendar_name": cal_name,
                "source_batch": "calendar_gov_2025",
            }
        )
        d += timedelta(days=1)

    df = pd.DataFrame(records)

    # Cast types
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["day_of_week"] = df["day_of_week"].astype("int8")
    df["is_holiday"] = df["is_holiday"].astype("int8")
    df["is_makeup_workday"] = df["is_makeup_workday"].astype("int8")
    df["is_school_break"] = df["is_school_break"].astype("int8")

    # Assertions
    assert df["date"].is_unique, "date not unique in dim_calendar!"
    n_holidays = df["is_holiday"].sum()
    print(
        f"[AUDIT] dim_calendar: rows={len(df)} holidays={n_holidays} makeup={df['is_makeup_workday'].sum()}"
    )

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, engine="pyarrow")
    fsize_kb = output_path.stat().st_size / 1024
    print(f"[AUDIT] dim_calendar written: {output_path} ({fsize_kb:.1f} KB)")

    return df


if __name__ == "__main__":
    build()
