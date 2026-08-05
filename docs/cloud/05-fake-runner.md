# 05 · FakeRunner

FakeRunner 的权威实现是
`apps/cloud_api/src/metro_cloud_api/runners/fake.py`，不再在 Markdown 中维护第二份可复制
代码，避免契约漂移。

它是结构测试替身，不是物理仿真证据。它会：

- 按运营流量比例分配 `enter_and_board`、`exit_station`、`transfer` intent；
- 疏散模式只生成 `evacuate_station`；
- 管理员只进入资源容量和 summary，不混入 passenger trajectories/person_count；
- 生成 source-anchored state/intent/stage 值；
- 使用命名空间字符串 event ID；
- 只写 horizon 内的 terminal/facility events；
- 对 progress 做 horizon clamp；
- 写两个 Parquet 和私有 `_result.json`。

已自动验证的边界：

| 边界 | 断言 |
|---|---|
| group_size=5，person=5 | passenger_agent_count=1，person_count=5 |
| evacuation person=50，group=5，admins=2 | passenger=10，total agent=12 |
| horizon=demand=5 | simulated_seconds=300 |
| sample=7，horizon=60s | 最终 progress 恰好 60/60 |
| worker 完成 | `_result.json` 被吸收进 summary 后删除 |

运行：

```powershell
$env:METRO_RUNNER='fake'
metro-cloud-api
metro-cloud-worker
```
