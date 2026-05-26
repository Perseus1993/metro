"""Station ID Registry — 站点 ID 注册表固化模块。

registry key = canonical_station_name(display_name)
只从 station_master.csv 写入，事实表永不写入。

用法:
    # Phase A — dim_station 构建时:
    reg = StationIdRegistry(registry_path, master_csv_path)
    sid = reg.get_or_create("北大街")   # 可写
    reg.save()

    # Phase B — fact_* 构建时:
    sid = reg.lookup("北大街")          # 只读, 找不到返回 None
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

_TZ_CST = timezone(timedelta(hours=8))


class StationIdRegistry:
    """站点 ID 注册表。

    - 首次构建时从 station_master.csv 初始化
    - 后续增量只给新站分配新 id, 绝不重排/回收
    - key = canonical station_name (from station_master)
    """

    def __init__(
        self,
        registry_path: str | Path,
        master_csv_path: str | Path,
    ) -> None:
        self._path = Path(registry_path)
        self._master_path = Path(master_csv_path)
        self._stations: dict[str, int] = {}
        self._next_id: int = 1
        self._meta: dict[str, Any] = {}
        self._dirty = False

        if self._path.exists():
            self._load()
        else:
            self._init_from_master()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(self, station_name: str) -> int:
        """仅用于 dim_station 构建阶段。

        station_name 必须来自 station_master.csv 的 canonical 名。
        """
        if station_name in self._stations:
            return self._stations[station_name]
        sid = self._next_id
        self._stations[station_name] = sid
        self._next_id += 1
        self._dirty = True
        return sid

    def lookup(self, station_name: str) -> int | None:
        """只读查询，事实表专用。找不到返回 None，调用方负责处理。"""
        return self._stations.get(station_name)

    def save(self) -> None:
        """持久化到 JSON。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(_TZ_CST).isoformat()
        if not self._meta.get("created"):
            self._meta["created"] = now
        self._meta["last_updated"] = now
        self._meta["next_id"] = self._next_id
        self._meta["version"] = self._meta.get("version", 1)
        payload = {
            "_meta": self._meta,
            "stations": dict(sorted(self._stations.items(), key=lambda kv: kv[1])),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False
        n = len(self._stations)
        print(f"[AUDIT] registry saved: path={self._path} stations={n} next_id={self._next_id}")

    def to_dataframe(self) -> pd.DataFrame:
        """返回 station_name → station_id 的 DataFrame。"""
        records = [
            {"station_name": name, "station_id": sid} for name, sid in self._stations.items()
        ]
        df = pd.DataFrame(records)
        if len(df) > 0:
            df = df.sort_values("station_id").reset_index(drop=True)
            df["station_id"] = df["station_id"].astype("int32")
        return df

    @property
    def station_count(self) -> int:
        return len(self._stations)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._meta = raw.get("_meta", {})
        self._stations = raw.get("stations", {})
        self._next_id = self._meta.get("next_id", 1)
        # 安全校验: next_id 必须大于所有已有 id
        if self._stations:
            max_existing = max(self._stations.values())
            if self._next_id <= max_existing:
                self._next_id = max_existing + 1
        n = len(self._stations)
        print(f"[AUDIT] registry loaded: path={self._path} stations={n} next_id={self._next_id}")

    def _init_from_master(self) -> None:
        """从 station_master.csv 初始化 registry。

        按 (primary_line_ref, display_name) 排序, 从 1 开始编号。
        """
        if not self._master_path.exists():
            raise FileNotFoundError(f"station_master.csv not found: {self._master_path}")

        rows: list[dict[str, str]] = []
        with self._master_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 规则 10: CSV 列名读入后必须 strip()
                row = {k.strip(): v.strip() for k, v in row.items()}
                rows.append(row)

        def _sort_key(r: dict[str, str]) -> tuple:
            """按 primary_line_ref (数字优先) + display_name 排序。"""
            refs = r.get("line_refs", "").split("|")
            primary = refs[0] if refs else ""
            if primary.isdigit():
                return (0, int(primary), r.get("name", ""))
            return (1, 0, r.get("name", ""))

        rows.sort(key=_sort_key)

        for idx, row in enumerate(rows, start=1):
            name = row.get("name", "").strip()
            if not name:
                continue
            self._stations[name] = idx

        self._next_id = len(self._stations) + 1
        self._dirty = True
        n = len(self._stations)
        print(f"[AUDIT] registry initialized from master: {self._master_path}")
        print(f"[AUDIT] stations={n} next_id={self._next_id}")
