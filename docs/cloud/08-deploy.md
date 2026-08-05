# 08 · 单机部署与验收

目标：Ubuntu ECS，2 vCPU / 4 GB 起步。该规格必须经目标机 spike 证明；不是容量事实。

## 网络边界

- FastAPI 只监听 `127.0.0.1:8000`。
- 安全组只开放 TCP 22，并使用实际维护者 IP 白名单；IP 变化时需要更新白名单。
- 禁止开放 8000，禁止为应用增加 `0.0.0.0/0` 入站规则。
- SSH 禁用密码和 root 登录，使用密钥。

用户访问：

```bash
ssh -N -L 8000:127.0.0.1:8000 pilot@HOST
```

SDK 连接 `http://127.0.0.1:8000`。HTTP 没有经过公网；可选 token 是纵深防御，不能
替代 SSH 隧道。

## 安装

```bash
sudo useradd --system --home /var/lib/metro-cloud --shell /usr/sbin/nologin metro-cloud
sudo install -d -o metro-cloud -g metro-cloud /var/lib/metro-cloud
sudo install -d -o metro-cloud -g metro-cloud /opt/metro

cd /opt/metro
UV_PROJECT_ENVIRONMENT=/opt/metro/.venv uv sync --locked \
  --package metro-cloud --extra real

sudo cp apps/cloud_api/deploy/metro-cloud.env.example /etc/metro-cloud.env
sudo cp apps/cloud_api/deploy/metro-cloud-api.service /etc/systemd/system/
sudo cp apps/cloud_api/deploy/metro-cloud-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now metro-cloud-api metro-cloud-worker
```

仓库同时提供幂等安装入口：

```bash
sudo METRO_REPO_DIR=/opt/metro bash apps/cloud_api/deploy/install.sh
```

环境模板默认 `METRO_RUNNER=real`、`METRO_MAX_AGENTS=50`、job timeout 暂定 14400 秒、
RSS 软闸门 3 GiB。worker systemd 单元另设 `MemoryMax=3G` 和
`KillMode=control-group`。如果整个 worker cgroup 被强杀，重启恢复负责把中断 job
标记为 `worker_lost` 并补写 summary；不承诺被 SIGKILL 的进程能执行 finally。

## 必须通过的部署验收

```bash
# 外部机器：必须失败
curl --max-time 5 http://HOST:8000/health

# 建隧道后：必须成功
curl http://127.0.0.1:8000/health

# 服务器：必须只见 127.0.0.1:8000
ss -lntp | grep 8000

# 服务状态和近期日志
systemctl status metro-cloud-api metro-cloud-worker
journalctl -u metro-cloud-worker -n 200 --no-pager
```

还必须执行：真实 50 人 job、cancel/timeout 整树清理、worker SIGKILL 恢复、连续 10
job、下载 SHA 校验以及磁盘余量检查。任何一项失败都保持 hold。

常规目标机验收会运行真实 HTTP E2E、四档 spike 和 10×50 soak：

```bash
sudo METRO_REPO_DIR=/opt/metro bash apps/cloud_api/deploy/verify.sh
```

维护窗口先执行 cancel/timeout 整树清理演练（会临时重启 worker），再执行强杀恢复
演练（会 SIGKILL worker 及其当前 child）：

```bash
sudo bash apps/cloud_api/deploy/verify-worker-faults.sh
sudo bash apps/cloud_api/deploy/verify-worker-recovery.sh
```

公网 8000 不可达必须从 ECS 外部机器检查；服务器本机无法证明安全组入站规则有效。

## 运维边界

该版本只承诺单用户、串行 worker、50 人 limited pilot。不承诺 60 分钟高峰、80 job
压测、无人值守稳定运维或 200 agent 性能；200 只是待 spike 验证的配置上限。
