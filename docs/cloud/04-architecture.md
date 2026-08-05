# 04 · 架构与进程接缝

## 运行模型

```text
SDK --SSH tunnel--> FastAPI --SQLite WAL--> serial worker --> runner process group
                           \-------------> /var/lib/metro-cloud/jobs/{id}
```

- API 只校验、入库、查询和发送文件，不执行仿真。
- worker 使用 `BEGIN IMMEDIATE` 原子领取最老 queued job，一次只运行一个。
- 每个 runner 在独立进程组执行；超时、取消和 RSS 超限都终止整个进程树。
- SQLite 与 job 目录是 API/worker 之间仅有的共享状态。

实现位于 `apps/cloud_api/src/metro_cloud_api/`。

## 唯一 runner 接缝

```python
class SimulationRunner(Protocol):
    kind: str
    version: str

    def run(self, spec: dict, output_dir: Path, on_progress: ProgressCallback) -> None: ...
```

`FakeRunner` 只依赖 PyArrow；`MetroStationRunner` 是唯一允许导入 `metro_station` 的后端
模块，并延迟加载。两者都写 `trajectories.parquet`、`events.parquet` 和私有
`_result.json`，都不写 summary。

统一入口：

```text
python -m metro_cloud_api.child <fake|real> <_runner_spec.json> <output_dir>
```

stdout 是逐行 JSON 协议：`meta`、`progress`、`error`；其他 stdout 只进入 `run.log`。

## worker 可靠性

stdout 由 reader thread 放入 queue，主线程不阻塞地执行：

1. `proc.poll()`；
2. monotonic wall-clock deadline；
3. `psutil` 对当前 PID 及所有子孙进程采样 RSS；
4. SQLite cancel flag；
5. 协议消息和进度持久化。

Linux 使用 `start_new_session=True` 和 `killpg`；Windows 开发测试使用 psutil 终止进程
树。不使用累计的 `RUSAGE_CHILDREN.ru_maxrss`。

worker 存活时在 `finally` 写 summary。SIGKILL/cgroup 杀死 worker 时不会执行 finally；
服务重启后扫描所有 `running` job，清理 partial/结果文件，写
`error.kind=worker_lost` 的 summary，再转 failed。只有 cgroup 或 journal 有明确证据时
才可把失败标为 OOM。

## 数据职责

- API：保存规范化的 `submitted_spec` JSON 对象和带默认值/派生量的 `resolved_spec`。
- runner：科学计算与原始结果。
- worker：状态、时序、runner metadata、错误、峰值 RSS 和最终 summary。
- SDK：等待、取消、SHA 缓存和 Range 续传。

默认上限与首发承诺均为 50 total agents。只有目标机 spike 通过后才用
`METRO_MAX_AGENTS` 上调到 100/200，不能绕过 API 校验。
