"""Canonical semantic fingerprints for versioned application contracts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from math import isfinite
from typing import Any, Mapping


def semantic_fingerprint(value: Any) -> str:
    canonical = json.dumps(
        canonical_semantic_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_semantic_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("semantic fingerprint does not support non-finite numbers")
        decimal = Decimal(str(value)).normalize()
        normalized = format(decimal, "f")
        return {"$number": "0" if normalized in {"-0", ""} else normalized}
    if isinstance(value, Mapping):
        return {str(key): canonical_semantic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_semantic_value(item) for item in value]
    raise ValueError(f"semantic fingerprint does not support {type(value).__name__}")
