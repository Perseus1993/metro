from __future__ import annotations

import json
from pathlib import Path

from metro_alignment.formal_contract import ladder_manifest_json_schema

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output = ROOT / "schemas" / "alignment_ladder_manifest.v1.schema.json"
    output.write_text(
        json.dumps(ladder_manifest_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
