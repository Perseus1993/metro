"""Build dim_station.parquet from station_master.csv + station_id_registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def build(
    registry_path: str | Path = "data/ods/station_id_registry.json",
    master_csv: str | Path = "output/xian_metro_station_master.csv",
    output_path: str | Path = "data/ods/dim_station.parquet",
) -> pd.DataFrame:
    from scripts.ods.station_id_registry import StationIdRegistry

    registry_path = Path(registry_path)
    master_csv = Path(master_csv)
    output_path = Path(output_path)

    # 1. Load / init registry
    reg = StationIdRegistry(registry_path, master_csv)

    # 2. Read master CSV
    df = pd.read_csv(master_csv, encoding="utf-8-sig")
    # 规则 10: CSV 列名读入后必须 strip()
    df.columns = df.columns.str.strip()

    # 3. Assign station_id via get_or_create (only place that writes to registry)
    df["station_id"] = df["name"].apply(reg.get_or_create).astype("int32")

    if reg.is_dirty:
        reg.save()

    # 4. Build output DataFrame
    out = pd.DataFrame(
        {
            "station_id": df["station_id"],
            "station_name": df["name"].astype(str),
            "display_name": df["display_name"].astype(str),
            "line_refs": df["line_refs"].fillna("").astype(str),
            "primary_line_ref": df["line_refs"].fillna("").str.split("|").str[0].astype(str),
            "lat": pd.to_numeric(df["lat"], errors="coerce"),  # missing → NaN
            "lon": pd.to_numeric(df["lon"], errors="coerce"),  # missing → NaN
            "coord_system": df["coord_system"].fillna("").astype(str),
            "has_coords": pd.to_numeric(df["lat"], errors="coerce").notna(),
        }
    )

    # 5. Assertions
    assert out["station_id"].is_unique, "station_id not unique!"
    assert out["station_name"].is_unique, "station_name not unique!"
    n_missing = (~out["has_coords"]).sum()
    print(f"[AUDIT] dim_station: rows={len(out)} missing_coords={n_missing}")

    # Verify NaN coords for missing stations
    missing_mask = ~out["has_coords"]
    assert out.loc[missing_mask, "lat"].isna().all(), "has_coords=False but lat not NaN"
    assert out.loc[missing_mask, "lon"].isna().all(), "has_coords=False but lon not NaN"

    # 6. Write parquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False, engine="pyarrow")
    fsize_kb = output_path.stat().st_size / 1024
    print(f"[AUDIT] dim_station written: {output_path} ({fsize_kb:.1f} KB)")

    return out


if __name__ == "__main__":
    build()
