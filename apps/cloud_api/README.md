# Metro Cloud limited pilot

单用户、串行 worker 的站内客流仿真 API。服务仅监听 `127.0.0.1:8000`，用户通过
SSH 本地端口转发访问。首发验收规模和默认配置上限均为 50 total agents；目标机
spike 通过后才允许上调到 100/200。

## 本地启动

```powershell
$env:UV_PROJECT_ENVIRONMENT='D:\metro\.venv-cloud'
uv sync --package metro-cloud --extra test --extra real
$env:METRO_DATA_DIR='D:\metro\tmp\metro-cloud'
uv run --package metro-cloud metro-cloud-api
uv run --package metro-cloud metro-cloud-worker
```

仅验证后端壳时设置 `METRO_RUNNER=fake`；真实仿真使用 `METRO_RUNNER=real`。

## SDK

```python
from metro_cloud import Client

with Client("http://127.0.0.1:8000") as client:
    job = client.submit({
        "entry_count_hour": 300,
        "exit_count_hour": 0,
        "transfer_count_hour": 0,
    })
    job.wait()
    job.download("summary.json")
```

## SSH 隧道

```bash
ssh -N -L 8000:127.0.0.1:8000 pilot@HOST
```

部署单元位于 `deploy/`。服务器安全组只开放 SSH，禁止开放 8000。
