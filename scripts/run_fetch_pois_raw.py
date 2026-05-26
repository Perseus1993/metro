"""
按站点缓冲区抓取全量 POI（入口脚本）。

用法: python -m scripts.run_fetch_pois_raw [--help]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.poi_fetcher_raw import main

if __name__ == "__main__":
    main()
