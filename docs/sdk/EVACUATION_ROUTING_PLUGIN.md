# 疏散路由插件 SDK（V0.2）

V0.2 只开放全局疏散路由插件。插件接收已经确定的起点、终点、动态关闭边、旅客群组、仿真时刻、算法种子和不可变拓扑，返回有序节点/边、成本、状态与诊断。插件不能改选出口或设施，不能更新旅客位置，也不能生成实验方案。

## 快速开始

复制 `examples/evacuation_routing_plugin/`，修改 `manifest.json` 和 `plugin.py`，然后运行：

```powershell
metro-station validate-routing-plugin examples/evacuation_routing_plugin/manifest.json
```

命令会在独立子进程中执行 10 个协议案例，覆盖正常路径、关闭边、无路、起终点相同、不同群组/种子和确定性复跑。退出码 `0` 表示全部通过。

## 清单

清单 schema 为 `algorithm-plugin/v1`，且必须声明：

- `kind`: 固定为 `evacuation_routing`
- `plugin_id`、`plugin_version`
- `api_version`: 固定为 `evacuation-routing/v1`
- `entry_point`: 不经 shell 执行的命令参数数组
- `parameter_schema`: JSON Schema Draft 2020-12 对象 schema
- `capabilities`: `closures`、`deterministic_seed`、`diagnostics`、`group_facts` 的子集

宿主会在启动插件前校验清单、兼容版本和参数。未知版本、能力或无效参数不会启动子进程。

## 进程协议

每次请求启动一个进程。宿主向标准输入写入一行 JSON：

```json
{"schema_version":"routing-plugin-invocation/v1","request":{}}
```

插件必须向标准输出写入且只写入一行 `EvacuationRoutingResponse` JSON。日志写到标准错误；标准输出中的调试文本会被视为协议错误。

请求/响应 schema、字段与校验规则以 `metro_station.application.routing_plugins` 为唯一事实来源。成功路径必须：

- 从请求的 `origin_node_id` 开始，在 `destination_node_id` 结束；
- 每一对相邻节点对应一个有向 `edge_id`；
- 不引用未知或关闭的边，不包含节点环；
- 返回有限且非负的 `cost`；
- 始终包含 `diagnostics`。

`no_route` 必须返回空节点、空边和 `null` 成本。插件超时、崩溃、非法 JSON、非法路径和缺失诊断会记录为失败决策，不会成为合法路由结果。

## 隔离边界

宿主会终止超时进程、等待子进程回收、捕获标准错误并为每次调用记录插件版本、参数、耗时、状态和决策日志。这是批次完整性隔离，不是针对不可信代码的安全沙箱；只运行经过审查的本地插件。
