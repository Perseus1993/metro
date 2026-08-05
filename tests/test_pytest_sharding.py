from __future__ import annotations

import pytest

from conftest import stable_shard_index


def test_stable_shard_index_partitions_each_node_once() -> None:
    nodeids = tuple(
        f"tests/test_example_{module}.py::test_case[{case}]"
        for module in range(512)
        for case in range(3)
    )
    shard_count = 64

    partitions = tuple(
        {
            nodeid
            for nodeid in nodeids
            if stable_shard_index(nodeid, shard_count) == shard_index
        }
        for shard_index in range(shard_count)
    )

    assert set().union(*partitions) == set(nodeids)
    assert sum(len(partition) for partition in partitions) == len(nodeids)
    assert all(partition for partition in partitions)


@pytest.mark.parametrize("shard_count", (0, -1))
def test_stable_shard_index_rejects_invalid_count(shard_count: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        stable_shard_index("tests/test_example.py::test_case", shard_count)
