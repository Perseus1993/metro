# 07 · 集成、容量与发布门禁

## 自动化基线

```powershell
D:\metro\.venv-cloud\Scripts\python.exe -m pytest apps/cloud_api/tests -q
D:\metro\.venv\Scripts\ruff.exe check apps/cloud_api
```

契约测试必须覆盖：

- 运营 50 人、group_size=5、管理员分离；
- 疏散人数整除、常规流量必须为 0；
- trajectory/event Arrow schema 和命名空间 event ID；
- sample 不整除 horizon 时 progress 不越界；
- API→SQLite→worker→summary→artifact；
- queued/running cancel、timeout、worker restart recovery；
- SDK checksum cache 与 Range resume。

## 真实 runner spike

必须在目标 ECS 上执行，每个规模都在新的进程中运行，避免累计 RSS 污染：

```bash
metro-cloud-spike --agents 25 50 100 200 \
  --timeout-seconds 14400 --output /tmp/metro-capacity-spike.json
```

脚本使用 psutil 采样当前 runner 及子孙进程，不使用 `RUSAGE_SELF` 或
`RUSAGE_CHILDREN`。每个 case 固定 10 分钟 demand、15 分钟 horizon、10 秒轨迹采样。

决策规则：

| 结果 | 决策 |
|---|---|
| 50 人成功且峰值 RSS/墙钟有安全余量 | 可进入 limited pilot |
| 100/200 失败 | 保持 `METRO_MAX_AGENTS=50`；不阻塞 50 人 pilot |
| 50 人失败或触及 MemoryMax/timeout | hold，先降规模或优化 |
| 任一 case 有孤儿进程、坏 Parquet、缺 summary | hold |

200 agent 只有 spike 成功后才是已验证能力；配置允许并不等于产品承诺。

连续 job soak：

```bash
metro-cloud-soak --jobs 10 --agents 50 --runner real \
  --horizon-minutes 15 --demand-minutes 10 \
  --output /tmp/metro-cloud-soak.json
```

2026-08-05 本机 soak：10/10 succeeded，总墙钟 421.547 秒，单 job 35.078～51.844
秒，峰值 RSS 706,318,336～769,847,296 bytes；所有 job 均有 6 个带 SHA 的公开产物，
Parquet 契约有效，SQLite 状态完整，私有 `_result.json` 已删除。证据见
`evidence/local-real-soak-10x50-2026-08-05.json`。目标 ECS 仍须复跑。

### 本机预检证据（非目标机结论）

首次 25-agent 预检曾在 progress 72/900 停滞，后确认是 spike harness 使用未消费的
stdout PIPE，逐步进度写满管道后阻塞 child；该结果已作废，不得当成仿真性能证据。
修复后 25/50/100/200 分别用 26.719/39.265/98.500/249.906 秒完成，峰值 RSS 分别为
714,063,872/740,323,328/856,666,112/1,165,721,600 bytes，全部通过 schema、行数、
排序和 agent/person 计数契约。证据见 `evidence/local-capacity-spike-2026-08-05.json`。
因此本机 50 与 200 implementation gate 均 pass；目标 ECS 未复跑前部署默认仍为 50。

本机真实 HTTP E2E 也已通过：SDK 提交 50-agent job，经 FastAPI、SQLite、worker 和
real child 成功；SDK 读取 pandas trajectories/events 和 summary，6 个产物 SHA 完整，
Range 返回 206。证据见 `evidence/local-real-http-e2e-50-2026-08-05.json`。

## 目标机故障演练

1. 运行中 cancel，确认 runner 进程组及所有子孙消失。
2. 把 timeout 临时设短，确认 `error.kind=timeout`、无 Parquet、存在 summary。
3. `systemctl kill -s SIGKILL metro-cloud-worker`，等待 systemd 重启；确认原 running
   job 变 failed，`error.kind=worker_lost`，并补出 summary。
4. 连续跑 10 个真实 50 人 job，检查 WAL、磁盘、RSS 和 SHA 下载。
5. 从公网请求 HOST:8000 必须超时；SSH 隧道内 `/health` 必须成功。

## 发布决定

三条轴分别判定：

- 产品价值：单一用户能提交、等待并下载可分析 Parquet。
- 仿真可信度：真实 runner、seed、spec、版本和限制可见；Fake 数据不当作仿真证据。
- 工程就绪：目标机 spike、故障恢复、网络边界、连续 10 job 全部通过。

三轴全部通过才记为 `limited pilot`；本版本不应标记为生产 ready。
