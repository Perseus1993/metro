# 03 · HTTP API 契约

版本：`v0.1`。序列化为 UTF-8 JSON。服务只监听 `127.0.0.1:8000`，通过 SSH
隧道访问；可选 `METRO_API_TOKEN` 仅作为隧道内的纵深防御。

实现位置：`apps/cloud_api/src/metro_cloud_api/api.py`。

## 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 存活探针；无需 token |
| GET | `/v1/catalog` | station、template、当前 agent 上限 |
| POST | `/v1/jobs` | 校验 JobSpec 并排队，成功返回 202 |
| GET | `/v1/jobs` | 按创建时间倒序列出 job |
| GET | `/v1/jobs/{id}` | 查询 job、进度、双份 spec 和错误 |
| POST | `/v1/jobs/{id}/cancel` | 取消 queued，或请求终止 running |
| GET | `/v1/jobs/{id}/artifacts` | 公开产物清单、大小与 SHA-256 |
| GET | `/v1/jobs/{id}/artifacts/{name}` | 白名单下载，支持 HTTP Range |

公开下载白名单只有：`submitted_spec.json`、`resolved_spec.json`、`summary.json`、
`run.log`、`trajectories.parquet`、`events.parquet`。`_runner_spec.json`、
`_result.json` 和 `*.partial` 永不公开。

## Job 对象

```json
{
  "id": "uuid4-hex",
  "status": "running",
  "submitted_spec": {},
  "resolved_spec": {"_derived": {}},
  "created_at": "2026-08-05T10:00:00+00:00",
  "started_at": "2026-08-05T10:00:02+00:00",
  "finished_at": null,
  "progress": {"current": 120, "total": 900},
  "queue_position": null,
  "runner": {"kind": "real", "version": "0.1.0"},
  "error": null
}
```

状态机：`queued → running → succeeded|failed|cancelled`，`queued → cancelled`。
running 取消由 worker 在轮询周期内终止整个进程树，因此是异步请求。

## 校验与安全

- Pydantic 拒绝未知字段；业务校验失败返回 400。
- catalog 不接受未知 station/template。
- 估算的 passenger agent + admin agent 超过 `METRO_MAX_AGENTS` 时返回 400。
- job 不存在或产物不在白名单时返回 404。
- 配置 token 后，除 `/health` 外必须发送 `Authorization: Bearer ...`。
- 文件下载先做固定白名单判断，再解析路径，不接受用户路径片段。

## 下载语义

清单返回 `name`、`size_bytes`、`sha256`。SDK 使用 SHA-256 命中本地缓存，未完成的
`.partial` 文件使用 Range 续传；服务端 `FileResponse` 提供 Range 响应。

失败和取消的 job 不公开 Parquet；诊断产物仍包括双份 spec、`run.log` 和
`summary.json`。
