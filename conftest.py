from __future__ import annotations

from hashlib import sha256

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("test sharding")
    group.addoption(
        "--shard-count",
        action="store",
        default=1,
        type=int,
        help="Split the collected root suite into this many stable shards.",
    )
    group.addoption(
        "--shard-index",
        action="store",
        default=0,
        type=int,
        help="Run this zero-based stable shard.",
    )


def stable_shard_index(nodeid: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    digest = sha256(nodeid.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big") % shard_count


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    shard_count = int(config.getoption("--shard-count"))
    shard_index = int(config.getoption("--shard-index"))
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise pytest.UsageError(
            "test shard must satisfy shard-count >= 1 and "
            "0 <= shard-index < shard-count"
        )
    if shard_count == 1:
        return

    selected = [
        item
        for item in items
        if stable_shard_index(item.nodeid, shard_count) == shard_index
    ]
    deselected = [item for item in items if item not in selected]
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
