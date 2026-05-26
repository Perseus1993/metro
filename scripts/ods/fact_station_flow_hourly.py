"""Build fact_station_flow_hourly.parquet — 站点小时客流事实表。

数据源: data/processed/station_flow_30min_2025H1.csv
处理: 读取 → registry.lookup() 映射 → 按 (date, hour, station_id) 聚合 → 审计 → 写 Parquet
站名映射使用 lookup() only。未匹配 → [AUDIT][UNMATCHED] → abort。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def build(
    registry_path: str | Path = "data/ods/station_id_registry.json",
    master_csv: str | Path = "output/xian_metro_station_master.csv",
    flow_csv: str | Path = "data/processed/station_flow_30min_2025H1.csv",
    output_path: str | Path = "data/ods/fact_station_flow_hourly.parquet",
    tmp_dir: str | Path = "data/ods/.tmp_build",
) -> pd.DataFrame:
    from scripts.ods.station_id_registry import StationIdRegistry

    registry_path = Path(registry_path)
    output_path = Path(output_path)
    tmp_dir = Path(tmp_dir)
    tmp_out = tmp_dir / output_path.name

    # 1. Load registry (lookup only)
    reg = StationIdRegistry(registry_path, master_csv)

    # 2. Read flow CSV
    print("[AUDIT] fact_station_flow_hourly: reading flow CSV ...")
    df = pd.read_csv(flow_csv, encoding="utf-8-sig")
    # 规则 10: CSV 列名读入后必须 strip()
    df.columns = df.columns.str.strip()
    print(f"[AUDIT] raw rows={len(df)}")

    # 3. Map station_name → station_id (lookup only!)
    unmatched: dict[str, int] = {}

    def _lookup(name: str) -> int:
        sid = reg.lookup(name)
        if sid is not None:
            return sid
        unmatched[name] = unmatched.get(name, 0) + 1
        return -1  # sentinel, will be caught by audit

    df["station_id"] = df["station_name"].apply(_lookup).astype("int32")

    # 4. Report unmatched
    if unmatched:
        for name, cnt in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            print(f"[AUDIT][UNMATCHED] station_name={name} count={cnt}")
        raise SystemExit(
            f"[FATAL] {len(unmatched)} unmatched stations found, "
            f"ODS build aborted. Fix station_master or raw data."
        )

    # 5. Aggregate 30min → hourly
    entry_mask = df["in_out"] == "进站"
    exit_mask = df["in_out"] == "出站"

    agg_entry = (
        df.loc[entry_mask]
        .groupby(["date", "hour", "station_id", "station_name"], observed=True)["passenger_count"]
        .sum()
        .rename("entry_count")
    )
    agg_exit = (
        df.loc[exit_mask]
        .groupby(["date", "hour", "station_id", "station_name"], observed=True)["passenger_count"]
        .sum()
        .rename("exit_count")
    )

    out = pd.merge(
        agg_entry.reset_index(),
        agg_exit.reset_index(),
        on=["date", "hour", "station_id", "station_name"],
        how="outer",
    )
    # 规则 9: left join 后 NaN 必须显式处理
    out["entry_count"] = out["entry_count"].fillna(0).astype("int64")
    out["exit_count"] = out["exit_count"].fillna(0).astype("int64")
    out["total_count"] = out["entry_count"] + out["exit_count"]

    # Cast types
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["hour"] = out["hour"].astype("int32")

    out["source_batch"] = "reports_batch3"
    out["batch_id"] = "2025H1"

    # 6. Audit assertions
    pk = out[["date", "hour", "station_id"]].apply(tuple, axis=1)
    assert pk.is_unique, "(date, hour, station_id) PK not unique!"
    assert (out["station_id"] >= 0).all(), "Negative station_id found (unmatched leak)!"
    print(f"[AUDIT] fact_station_flow_hourly: rows={len(out)} PK_unique=True")

    # 7. Write to tmp then backup-replace
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(tmp_out, index=False, engine="pyarrow")

    # Backup replace
    _backup_replace(tmp_out, output_path)

    fsize_kb = output_path.stat().st_size / 1024
    print(f"[AUDIT] fact_station_flow_hourly written: {output_path} ({fsize_kb:.1f} KB)")

    return out


def _backup_replace(tmp_path: Path, formal_path: Path) -> None:
    """Best-effort backup replace: old→bak, tmp→formal, delete bak."""
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    bak_path = formal_path.with_suffix(formal_path.suffix + ".bak")

    # Step 1: old → bak
    if formal_path.exists():
        if bak_path.exists():
            bak_path.unlink()
        formal_path.rename(bak_path)

    # Step 2: tmp → formal
    try:
        tmp_path.rename(formal_path)
    except OSError as exc:
        # Rollback
        if bak_path.exists() and not formal_path.exists():
            bak_path.rename(formal_path)
        raise SystemExit(f"[AUDIT][FAILED] rename failed: {exc}") from exc

    # Step 3: delete bak
    if bak_path.exists():
        bak_path.unlink()


if __name__ == "__main__":
    build()
