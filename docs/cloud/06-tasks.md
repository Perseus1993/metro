# 06 · 实施清单与当前证据

状态更新：2026-08-05。

## 已实现并有自动化测试

- [x] JobSpec 未知字段拒绝、catalog、运营/疏散条件校验。
- [x] passenger/admin 分离的纯算术容量闸门，首发 total agent 上限 50。
- [x] submitted/resolved 双记录与 JSON 文件。
- [x] SQLite WAL、原子 claim、串行 worker、queued/running 取消。
- [x] FakeRunner、统一 child 入口、stdout 协议和 Parquet schema。
- [x] reader thread + queue，超时、进程树 RSS、整树终止。
- [x] 成败 summary；worker 重启恢复 running job 并补 summary。
- [x] 8 个 API 路由、loopback 默认、可选 bearer token、下载白名单。
- [x] SDK submit/query/wait/cancel、SHA 缓存、`.partial` + Range 续传。
- [x] systemd API/worker 单元和环境变量模板。

当前自动化命令：

```powershell
D:\metro\.venv-cloud\Scripts\python.exe -m pytest apps/cloud_api/tests -q
D:\metro\.venv\Scripts\ruff.exe check apps/cloud_api
```

当前证据：30 tests passed；Ruff/Pyright/锁文件检查/build passed；三份部署脚本通过
Bash 语法检查。真实 runner 的本机
25/50/100/200 agent、900 秒 horizon 均通过 Parquet 契约；50 agent 用 39.265 秒、
峰值 740,323,328 bytes，200 agent 用 249.906 秒、峰值 1,165,721,600 bytes。
这是本机容量证据，不等于目标 ECS 结论。

## 发布前仍需执行

- [x] 本机跑 25/50/100/200 agent 独立进程 spike并验证完整产物契约。
- [ ] 在目标 Linux ECS 复跑同一 spike。
- [x] 本机真实 50-agent runner 走完整 SDK→API→SQLite→worker→下载/Range/pandas 链路。
- [ ] Linux 实测 timeout/cancel 后无孤儿进程。
- [ ] `systemctl kill -s SIGKILL metro-cloud-worker` 后验证重启恢复 summary。
- [x] 本机连续 10 个真实 50-agent job，检查 RSS、SQLite、产物契约、SHA 与私有文件清理。
- [ ] 目标 ECS 复跑连续 10 个真实 50-agent job，并检查磁盘/cgroup。
- [ ] 完成 SSH-only 网络验收：公网 8000 超时，隧道内 health 成功。

只有以上目标机检查完成后，`RELEASE_REVIEW` 才能从 hold 改为 limited pilot。
