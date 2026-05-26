from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd
from openpyxl import Workbook

from scripts.etl.parse_od_reports import write_reports
from scripts.ods import fact_od_pair_60min
from scripts.ods.build_ads import build_od_network_panel
from src.amap_network import get_amap_key


class DataPipelineFixTests(unittest.TestCase):
    def test_od_etl_summary_keeps_zero_od_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            report = root / "线网OD统计分析报表-分时段-unit.xlsx"

            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "unit"
            worksheet.append([None, "2025年1月1日"])
            for _ in range(5):
                worksheet.append([])
            worksheet.append([None, None, None, "B"])
            worksheet.append(["02:00-03:00", "1号线", "A", 0])
            workbook.save(report)

            detail_csv = root / "detail.csv"
            summary_csv = root / "summary.csv"
            detail_rows, summary_rows = write_reports(root, detail_csv, summary_csv)

            self.assertEqual(0, detail_rows)
            self.assertEqual(1, summary_rows)
            with summary_csv.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(
                [{"date": "2025-01-01", "hour": "2", "od_total": "0", "nonzero_od_pairs": "0"}],
                rows,
            )

    def test_od_network_panel_left_joins_weather_calendar_and_fills_zero_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fact_dir = root / "fact_od_pair_60min"
            month_dir = fact_dir / "month=2025-01"
            month_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2025-01-01").date(),
                        "hour": 1,
                        "od_count": 7,
                    }
                ]
            ).to_parquet(month_dir / "part.parquet", index=False, engine="pyarrow")

            ads_path = root / "ads_od_network_hourly_panel.parquet"
            tmp_build = root / "tmp"
            tmp_build.mkdir()

            class Paths:
                fact_od_pair_60min = fact_dir
                ads_od_network_hourly_panel = ads_path

            weather_calendar = pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2025-01-01").date(),
                        "hour": 1,
                        "temperature_2m": 1.0,
                        "day_of_week": 3,
                    },
                    {
                        "date": pd.Timestamp("2025-01-01").date(),
                        "hour": 2,
                        "temperature_2m": 1.5,
                        "day_of_week": 3,
                    },
                ]
            )

            with mock.patch(
                "scripts.ods.build_ads.ODS.fact_station_flow_hourly",
                return_value=weather_calendar[["date", "hour"]],
            ):
                rows = build_od_network_panel(Paths, tmp_build, weather_calendar)
            out = pd.read_parquet(ads_path, engine="pyarrow").sort_values("hour")

            self.assertEqual(2, rows)
            self.assertEqual([7, 0], out["od_total"].tolist())

    def test_fact_od_build_aggregates_across_chunks_without_full_concat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            registry = root / "registry.json"
            registry.write_text(
                json.dumps({"_meta": {"next_id": 4}, "stations": {"A": 1, "B": 2, "C": 3}}),
                encoding="utf-8",
            )
            master = root / "master.csv"
            master.write_text("name,line_refs\nA,1\nB,1\nC,1\n", encoding="utf-8")
            od_csv = root / "od.csv"
            od_csv.write_text(
                "\n".join(
                    [
                        "date,hour,origin_station,destination_station,od_count,origin_line",
                        "2025-01-01,2,A,B,3,1号线",
                        "2025-01-01,2,A,B,4,2号线",
                        "2025-02-01,3,A,C,5,1号线",
                    ]
                ),
                encoding="utf-8",
            )
            out_dir = root / "out"
            tmp_build = root / "tmp"

            with mock.patch.object(fact_od_pair_60min, "CHUNKSIZE", 1):
                rows = fact_od_pair_60min.build(
                    registry_path=registry,
                    master_csv=master,
                    od_csv=od_csv,
                    output_dir=out_dir,
                    tmp_dir=tmp_build,
                )

            self.assertEqual(2, rows)
            jan = pd.read_parquet(out_dir / "month=2025-01", engine="pyarrow")
            self.assertEqual([7], jan["od_count"].tolist())
            self.assertEqual([1], jan["origin_station_id"].tolist())
            self.assertEqual([2], jan["destination_station_id"].tolist())

    def test_get_amap_key_requires_explicit_or_environment_key(self) -> None:
        env_names = ("AMAP_API_KEY", "AMAP_KEY", "GAODE_API_KEY", "GAODE_KEY")
        original = {name: os.environ.get(name) for name in env_names}
        try:
            for name in env_names:
                os.environ.pop(name, None)
            with self.assertRaises(RuntimeError):
                get_amap_key()

            os.environ["GAODE_KEY"] = "unit-key"
            self.assertEqual("unit-key", get_amap_key())
            self.assertEqual("explicit-key", get_amap_key("explicit-key"))
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
