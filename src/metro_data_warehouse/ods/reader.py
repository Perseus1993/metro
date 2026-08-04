"""ODS/ADS reader — 强注册的数据访问入口。

所有分析脚本应通过这里读取 ODS/ADS 数据，避免直接读 data/processed/*.csv。
"""

# NOTE: 本文件是库代码，未来应迁移至 src/metro/warehouse/ods_reader.py。

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


def _default_data_root() -> Path:
    configured = os.environ.get("METRO_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = (Path.cwd(), *Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "data" / "ods").exists():
            return candidate
    return Path.cwd()


def _fatal(message: str) -> "None":
    raise SystemExit(message)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fatal(f"[AUDIT][FATAL] missing json: {path}")
    except json.JSONDecodeError as exc:
        _fatal(f"[AUDIT][FATAL] invalid json: {path} err={exc}")


def _require_exists(path: Path) -> None:
    if not path.exists():
        _fatal(f"[AUDIT][FATAL] missing path: {path}")


def _manifest_path(table_path: Path) -> Path:
    if table_path.is_dir():
        return table_path / "_manifest.json"
    return table_path.with_name(f"{table_path.stem}_manifest.json")


def _validate_manifest(table_path: Path) -> dict:
    manifest = _manifest_path(table_path)
    payload = _read_json(manifest)
    if not payload.get("pk_unique", False):
        _fatal(f"[AUDIT][FATAL] pk_unique=false in manifest: {manifest}")
    return payload


def _import_pyarrow():
    try:
        import pyarrow.dataset as ds  # noqa: F401
        import pyarrow.parquet as pq  # noqa: F401
    except Exception as exc:
        _fatal(
            "[AUDIT][FATAL] pyarrow is required to read parquet. "
            f"import error={type(exc).__name__}: {exc}"
        )


def _months_filter_expr(months: Sequence[str]):
    # pyarrow expression is created lazily to avoid importing pyarrow at module import time
    import pyarrow.dataset as ds

    return ds.field("month").isin(list(months))


def _read_parquet(
    table_path: Path,
    *,
    columns: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
) -> "object":
    """Read parquet to pandas DataFrame.

    For partitioned datasets, pass months=["YYYY-MM", ...] to filter by month partition.
    """
    _import_pyarrow()
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    if table_path.is_dir():
        dataset = ds.dataset(str(table_path), format="parquet", partitioning="hive")
        filter_expr = _months_filter_expr(months) if months else None
        table = dataset.to_table(columns=list(columns) if columns else None, filter=filter_expr)
        return table.to_pandas()

    table = pq.read_table(str(table_path), columns=list(columns) if columns else None)
    return table.to_pandas()


@dataclass(frozen=True)
class ODSPaths:
    root: Path

    @property
    def ods_dir(self) -> Path:
        return self.root / "data" / "ods"

    @property
    def ads_dir(self) -> Path:
        return self.root / "data" / "ads"

    # ODS
    @property
    def dim_station(self) -> Path:
        return self.ods_dir / "dim_station.parquet"

    @property
    def dim_calendar(self) -> Path:
        return self.ods_dir / "dim_calendar.parquet"

    @property
    def dim_weather_hourly(self) -> Path:
        return self.ods_dir / "dim_weather_hourly.parquet"

    @property
    def fact_station_flow_hourly(self) -> Path:
        return self.ods_dir / "fact_station_flow_hourly.parquet"

    @property
    def fact_section_flow_hourly(self) -> Path:
        return self.ods_dir / "fact_section_flow_hourly"

    @property
    def fact_od_pair_60min(self) -> Path:
        return self.ods_dir / "fact_od_pair_60min"

    @property
    def station_id_registry(self) -> Path:
        return self.ods_dir / "station_id_registry.json"

    # ADS
    @property
    def ads_station_hourly_panel(self) -> Path:
        return self.ads_dir / "ads_station_hourly_panel.parquet"

    @property
    def ads_section_hourly_panel(self) -> Path:
        return self.ads_dir / "ads_section_hourly_panel.parquet"

    @property
    def ads_network_hourly_panel(self) -> Path:
        return self.ads_dir / "ads_network_hourly_panel.parquet"

    @property
    def ads_od_network_hourly_panel(self) -> Path:
        return self.ads_dir / "ads_od_network_hourly_panel.parquet"


class ODS:
    """Strong-registered access to ODS/ADS tables."""

    _ROOT = _default_data_root()
    _PATHS = ODSPaths(root=_ROOT)

    # ─────────────────────────────────────────────
    # Low-level
    # ─────────────────────────────────────────────
    @classmethod
    def _read_table(
        cls,
        table_path: Path,
        *,
        columns: Optional[Sequence[str]] = None,
        months: Optional[Sequence[str]] = None,
        validate_manifest: bool = True,
    ):
        _require_exists(table_path)
        if validate_manifest:
            _validate_manifest(table_path)
        df = _read_parquet(table_path, columns=columns, months=months)
        print(f"[AUDIT] read {table_path} rows={len(df)}")
        return df

    @classmethod
    def registry(cls) -> dict:
        _require_exists(cls._PATHS.station_id_registry)
        return _read_json(cls._PATHS.station_id_registry)

    # ─────────────────────────────────────────────
    # ODS dims
    # ─────────────────────────────────────────────
    @classmethod
    def dim_station(cls):
        return cls._read_table(cls._PATHS.dim_station)

    @classmethod
    def dim_calendar(cls):
        return cls._read_table(cls._PATHS.dim_calendar)

    @classmethod
    def dim_weather_hourly(cls, *, hour: Optional[int] = None):
        df = cls._read_table(cls._PATHS.dim_weather_hourly)
        if hour is not None:
            df = df[df["hour"].astype(int) == int(hour)].copy()
            print(f"[AUDIT] dim_weather_hourly filter hour={hour} rows={len(df)}")
        return df

    # ─────────────────────────────────────────────
    # ODS facts
    # ─────────────────────────────────────────────
    @classmethod
    def fact_station_flow_hourly(cls):
        return cls._read_table(cls._PATHS.fact_station_flow_hourly)

    @classmethod
    def fact_section_flow_hourly(cls, *, months: Optional[Sequence[str]] = None):
        return cls._read_table(cls._PATHS.fact_section_flow_hourly, months=months)

    @classmethod
    def fact_od_pair_60min(cls, *, months: Optional[Sequence[str]] = None):
        if months is None:
            print(
                "[AUDIT][WARN] reading full OD fact without month filter can be very large. "
                "Pass months=['YYYY-MM', ...] to filter."
            )
        return cls._read_table(cls._PATHS.fact_od_pair_60min, months=months)

    # ─────────────────────────────────────────────
    # ADS panels
    # ─────────────────────────────────────────────
    @classmethod
    def station_panel(cls):
        return cls._read_table(cls._PATHS.ads_station_hourly_panel)

    @classmethod
    def section_panel(cls):
        return cls._read_table(cls._PATHS.ads_section_hourly_panel)

    @classmethod
    def network_panel(cls):
        return cls._read_table(cls._PATHS.ads_network_hourly_panel)

    @classmethod
    def od_network_panel(cls):
        return cls._read_table(cls._PATHS.ads_od_network_hourly_panel)
