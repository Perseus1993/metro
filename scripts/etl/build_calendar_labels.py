"""Build calendar labels for 2025H1 (Jan 1 – Jun 30).

Source: 国务院办公厅2025年节假日安排 (中国政府网).

Output: data/processed/calendar_labels_2025H1.csv
  Columns: date, day_of_week, is_holiday, is_makeup_workday,
           is_school_break, calendar_type, calendar_name
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.etl.paths import STAGING_CALENDAR_LABELS  # noqa: E402

# ─────────────────────────────────────────────
# 法定节假日与调休日（硬编码来源已核实）
# ─────────────────────────────────────────────
HOLIDAYS: list[tuple[date, date, str]] = [
    (date(2025, 1, 1), date(2025, 1, 1), "元旦"),
    (date(2025, 1, 28), date(2025, 2, 4), "春节"),
    (date(2025, 4, 4), date(2025, 4, 6), "清明节"),
    (date(2025, 5, 1), date(2025, 5, 5), "劳动节"),
    (date(2025, 5, 31), date(2025, 6, 2), "端午节"),
]

MAKEUP_WORKDAYS: list[tuple[date, str]] = [
    (date(2025, 1, 26), "春节补班"),  # 周日
    (date(2025, 2, 8), "春节补班"),  # 周六
    (date(2025, 4, 27), "劳动节补班"),  # 周日
]

# 寒假近似区间（弱标记，不硬排除）
SCHOOL_BREAK_START = date(2025, 1, 15)
SCHOOL_BREAK_END = date(2025, 2, 28)

# ─────────────────────────────────────────────
# 日历生成
# ─────────────────────────────────────────────
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 6, 30)


def _build_holiday_map() -> dict[date, str]:
    hmap: dict[date, str] = {}
    for start, end, name in HOLIDAYS:
        d = start
        while d <= end:
            hmap[d] = name
            d += timedelta(days=1)
    return hmap


def _build_makeup_map() -> dict[date, str]:
    return {d: name for d, name in MAKEUP_WORKDAYS}


def build_calendar(output_csv: Path) -> int:
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    holiday_map = _build_holiday_map()
    makeup_map = _build_makeup_map()

    fieldnames = [
        "date",
        "day_of_week",
        "dow_name",
        "is_holiday",
        "is_makeup_workday",
        "is_school_break",
        "calendar_type",
        "calendar_name",
    ]

    rows_written = 0
    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        d = START_DATE
        while d <= END_DATE:
            dow = d.weekday()  # 0=Mon ... 6=Sun
            is_holiday = d in holiday_map
            is_makeup = d in makeup_map
            is_school_break = SCHOOL_BREAK_START <= d <= SCHOOL_BREAK_END

            if is_holiday:
                cal_type = "holiday"
                cal_name = holiday_map[d]
            elif is_makeup:
                cal_type = "makeup_workday"
                cal_name = makeup_map[d]
            elif dow >= 5:  # 周六日
                cal_type = "weekend"
                cal_name = ""
            else:
                cal_type = "workday"
                cal_name = ""

            writer.writerow(
                {
                    "date": d.isoformat(),
                    "day_of_week": dow,
                    "dow_name": DOW_NAMES[dow],
                    "is_holiday": int(is_holiday),
                    "is_makeup_workday": int(is_makeup),
                    "is_school_break": int(is_school_break),
                    "calendar_type": cal_type,
                    "calendar_name": cal_name,
                }
            )
            rows_written += 1
            d += timedelta(days=1)

    print(f"[AUDIT] output={output_csv}")
    print(f"[AUDIT] rows={rows_written}")
    print(f"[AUDIT] holidays={sum(1 for v in holiday_map.values())}")
    print(f"[AUDIT] makeup_workdays={len(makeup_map)}")
    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate calendar labels (holidays, makeup workdays, school breaks) for 2025H1."
    )
    parser.add_argument(
        "--output",
        default=str(STAGING_CALENDAR_LABELS),
    )
    args = parser.parse_args()
    build_calendar(Path(args.output))


if __name__ == "__main__":
    main()
