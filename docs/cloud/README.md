# 云端仿真服务 v0.1 —— 开发文档

> **给后端同学**：你不需要看懂这个仓库里任何仿真代码。你要建的是一个壳子。
> 按顺序读 `00` → `06`，第 6 篇是你的任务清单。有疑问先查 `01/02/03` 三份契约，那是唯一的事实来源。

---

## 这是什么

一个把「跑一次地铁站客流仿真」变成 HTTP 接口的薄服务。用户提交一组参数，服务在云主机上跑仿真，产出可以直接 `pd.read_parquet` 的轨迹数据。

**定位**：single-user limited pilot。`docs/product/RELEASE_REVIEW.md` 中 V0.2 发布决定仍为
**hold**，本服务不构成云端生产能力的证明。

**上线日期**：2026-08-25（**15 个工作日**，不是 20 天）
**首批用户**：1 人
**场景规模**：首发承诺与默认上限均为 50 total agents；200 是待目标机 spike 的候选

---

## 当前状态 ⚠️

**契约（`01`/`02`）尚未冻结。** 冻结前置条件是 8/05–8/06 的 2 天技术尖峰，8/07 评审。

尖峰要回答的头号问题：**50 人场景 5/15/30 分钟的峰值内存到底是多少**
（`simulation_lifecycle.py` 的 `run()` 把全部 frames 攒在内存里返回）。

尖峰不过 → 契约不冻结 → 重新评估范围。详见 `07-integration.md` 第一部分。

壳子部分（API、job 存储、worker、下载、部署）不依赖尖峰结果，**8/05 就可以开工**。

---

## 文档索引

| 文件 | 内容 | 谁必读 |
|---|---|---|
| [00-scope.md](00-scope.md) | 目标、非目标、分工边界、名词表 | 全员 |
| [01-jobspec.md](01-jobspec.md) | **契约**：请求参数白名单与校验规则 | 全员 |
| [02-outputs.md](02-outputs.md) | **契约**：产物文件与 parquet schema | 全员 |
| [03-api.md](03-api.md) | **契约**：HTTP 端点、状态码、错误格式 | 后端、SDK |
| [04-architecture.md](04-architecture.md) | 组件、进程模型、代码布局、**那条接缝** | 后端 |
| [05-fake-runner.md](05-fake-runner.md) | 假仿真器完整代码，复制即用 | 后端 |
| [06-tasks.md](06-tasks.md) | 后端逐日任务 + 验收标准 | 后端 |
| [07-integration.md](07-integration.md) | 联调日：把假的换成真的 | 全员 |
| [08-deploy.md](08-deploy.md) | 阿里云部署 | 后端 |

`fixtures/` 放示例请求和示例产物，可以直接拿去写测试。

---

## 并行开发怎么做到的

整个设计只有**一条接缝**：

```python
class SimulationRunner(Protocol):
    def run(self, spec: dict, output_dir: Path, on_progress) -> None: ...
```

- **后端同学**建整个壳子（API、任务队列、存储、下载、SDK、部署），接缝背后挂一个**假 runner**——睡几秒，吐出格式正确的假 parquet。
- **仿真侧**实现**真 runner**——通过现有 application executor 运行并转换同格式 parquet。
- 两边都对着 `01/02` 两份契约写，中间不需要沟通。
- 联调日就是把 `METRO_RUNNER=fake` 改成 `METRO_RUNNER=real`。

除 `runners/metro_station.py` 这一真实适配模块外，后端代码禁止 `import metro_station`；
仓库测试用 AST 守住该边界。

---

## 契约冻结规则

`01-jobspec.md` 和 `02-outputs.md` 是 v0.1 唯一不能返工的东西。

- 冻结日期：**2026-08-05**。真实 runner 的本机四档尖峰、同构产物契约和完整
  HTTP E2E 已通过；目标机容量是部署上限门禁，不再改变 v0.1 字段契约。
- 冻结后要改：必须双方同意，且在文档底部 CHANGELOG 追加一行。
- 不允许静默改字段名或类型。

---

## 评审修订记录

2026-08-05 收到师兄只读评审，6 条 P0 全部核实成立，已逐条修订：

| # | 问题 | 修订 | 落在 |
|---|---|---|---|
| P0-1 | 时长语义冲突（`minutes+clearance` vs `max(minutes, demand+clearance)`） | 改 `horizon_minutes` / `demand_minutes` 两个权威字段，clearance 派生 | `01` `05` |
| P0-2 | 真 runner 路径没闭合（CLI 只出可视化 payload） | 改 in-process `executor.execute()`，不调 CLI | `07` |
| P0-3 | `phase` 是编造的字段；facility event 一对多 | 换成 `state`/`intent`/`goal_*` 并标注源码出处；events 按 `passenger_ids` explode | `02` `05` `07` |
| P0-4 | 容量闸门在 API 层算不出来 | 客流三字段改必填，闸门变纯算术；新增 submitted/resolved 双记录 | `01` `04` |
| P0-5 | 内存风险未验证 | 规模压到 50 人（约 400 MB）；尖峰实测三档容量表后才定阈值 | `00` `07` |
| P0-6 | 失败产物与子进程协议冲突 | 统一 `child.py` 入口；`summary.json` 改由 worker 兜底写；进程组终止 | `02` `04` |
| 附 | Ubuntu 22.04 无 python3.12；uv 路径不一致 | 改 uv 托管 Python + 显式 `UV_INSTALL_DIR` + 当场验证 | `08` |
| 附 | 无 HTTPS 的 token 保护不了 token | 改 **SSH 隧道**，8000 不对公网开放 | `08` |
| 附 | 工期按 20 天排，实际只有 15 个工作日 | 重排时间线 + 明确「承诺什么／不承诺什么」 | `00` |

---

## 状态

| | 负责人 | 状态 |
|---|---|---|
| 技术尖峰（8/05–8/06） | gen | **未开始，阻塞契约冻结** |
| 契约冻结（8/07） | gen | 待尖峰 |
| 壳子（API/worker/SDK/部署） | 后端同学 | 可以开工 |
| 真 runner（parquet 导出器） | gen | 待尖峰 |
