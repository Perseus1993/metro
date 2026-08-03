# PM-028-E6 规模、分片与浸泡试探包

- 优先级：P2
- 状态：`implemented / v2 smoke+shard+resume+soak passed / v2 nightly+release not executed`
- 当前v2证据：64个smoke静态 + 12个smoke仿真通过；1/2/4分片一致；真实中断续跑通过；4类重场景×2重复浸泡通过
- 历史v1证据：2,000个nightly静态案例通过，约216秒
- 未执行：v2的2,000静态+150仿真nightly；10,000静态+300仿真release

## 要回答的问题

E6验证既有生成式验收在目标硬件上扩大规模后，是否仍保持零静默失败、确定性、合理运行时、受控内存和可合并证据。它不负责发现E1～E5尚未定义的拓扑语义。

## 实际结论（2026-07-18）

- `constraint_layout_generator.v2` 已把五类footprint、FULL/CHAIN/DUAL_CLUSTER和双向/进出分离纳入静态语料与分层仿真抽样；
- 主命令支持 `--shard-index/--shard-count/--resume-from`，逐案例checkpoint不会被续跑覆盖；merge工具验证重复、遗漏、错误分片和canonical fingerprint；
- 同一64案例语料按1、2、4分片实际重复生成后canonical结果一致；CLI两分片合并及强制中断续跑通过；
- fresh smoke静态64/64耗时23.99秒，traced peak 1.70MB，最终RSS 139.55MB；12/12仿真通过；manifest标记dirty worktree；
- 三层六电梯密集瓶颈、瓶颈站厅、双连接簇、需求—故障耦合各执行基线/比较两次，人员核算误差0、无子进程泄漏、20%相对回归门禁通过；
- 这些结果建立工程机制和smoke基线，不替代尚未调度的v2 nightly/release完整运行。

## 前置条件

- E1核心拓扑、E2边界和E4测试敏感性通过；
- 所有P0 `AUDIT` 已决定；
- 目标硬件、OS、Python、浏览器、movement backend和依赖锁文件版本写入run manifest；
- release运行期间不修改代码、依赖、案例目录或阈值；
- 输出磁盘空间预检通过。

## 三个规模档位

沿用现有生成验收档位，不建立第二套含义冲突的profile：

| 档位 | 静态场景 | 仿真分层样本 | 种子 | 当前状态 |
|---|---:|---:|---|---|
| smoke | 64 | 12 | 42 | v2 fresh run已执行通过 |
| nightly | 2,000 | 150 | 41、42、43 | v1静态历史通过；v2完整档位待执行 |
| release | 10,000 | 300 | 41、42、43 | v2待执行 |

所有静态场景执行设计、拓扑、队列、回放、资产绑定和往返门禁；仿真只对分层样本执行四旅程、确定性复跑、疏散和对应运营profile。

## 覆盖与分层抽样

静态语料报告至少覆盖：

- 4个现有archetype和E1新增的稳定topology archetype；
- 1～3层；
- 1～4入口、1～2闸机组、0～6电梯；
- 楼梯/扶梯有无；
- mirror true/false；
- sparse/standard/dense；
- 五类operation profile；
- E1平面、跨层和付费区因子。

仿真抽样在现有archetype、电梯数、operation profile和asset density之外，必须加入E1拓扑形态、跨层方式、付费区方式。报告列出单值和强制二元组合覆盖，不能只写sample count。

## 运行阶段

### S1：nightly完整补跑

执行2,000静态 + 150分层仿真样本，种子41/42/43。目标是补齐PM-028已有证据缺口。静态语料若生成器版本未变化，可引用已有run，但仿真必须与确切corpus fingerprint绑定。

### S2：release静态

执行10,000静态案例，成功案例只保存recipe和摘要；失败案例保存完整产物。至少重复一次同corpus运行，确认case顺序、设计指纹和失败集合一致。

### S3：release仿真

对300个分层样本使用种子41/42/43。每个样本运行四旅程、确定性复跑、疏散和一个operation profile。报告必须区分“300个recipe样本”和其内部实际运行次数。

### S4：分片一致性

将同一10,000 corpus按 `recipe_id` 稳定分为1、2、4个shard。分别运行并用正式merge工具合并，验证：

- 无重复或遗漏case；
- 合并顺序不改变canonical summary；
- 每个case设计指纹与串行运行一致；
- 失败证据不会被后写入的shard覆盖；
- 总通过率、覆盖统计和失败集合一致。

### S5：浸泡与内存

选择4个最重代表场景：三层六电梯密集资产、瓶颈站厅、双连接簇、需求—故障组合。每个执行长时运行或重复批次，使用已有性能/soak框架记录：

- wall time和real-time factor；
- Python traced peak memory和进程RSS；
- 每固定批次GC后的驻留内存；
- 帧/快照/轨迹点数量；
- 人员核算误差和设施事件数量；
- 文件句柄、子进程和浏览器进程是否回收。

第一轮建立基线；第二轮同硬件同版本不得比基线wall time或峰值内存回归超过20%，否则进入review。绝对性能预算必须绑定目标硬件后再冻结。

## 暂定当前工作站预算

已有2,000静态约216秒，线性外推10,000约18分钟。首次release静态暂设30分钟review线，作为调度预算而非产品承诺：

- 10,000静态零失败、设计唯一率100%；
- 总wall time不超过30分钟，否则记录瓶颈并重新评审CI策略；
- 每1,000例记录吞吐和RSS；后半程吞吐不得持续恶化超过20%；
- GC后RSS从首个稳定检查点到末检查点增长不超过100MB，否则进入泄漏调查；
- 不因达到时间预算而跳过剩余案例。

仿真总时长目前证据不足，不先虚构绝对release门槛。首次完整nightly作为基线，随后冻结同硬件预算。

## 确定性与复现

- corpus fingerprint、generator version、git commit、dirty状态和依赖锁hash进入manifest；
- 相同case和seed的设计、canonical topology、场景、资产、运行摘要指纹一致；
- wall time、临时路径和生成时间不参与语义指纹；
- 不同seed必须达到声明的设计多样性，不允许大量重复设计伪装成规模覆盖；
- 串行、分片和合并后的canonical结果一致。

## 失败与续跑

- 进程中断后按已完成case ID续跑，不重写已完成证据；
- 续跑manifest记录父run ID、缺失范围和原因；
- 任何失败均不阻止收集其他独立case，但最终状态为review；
- OOM、超时、子进程泄漏、证据写入失败和fingerprint不一致都是工程失败；
- 不允许自动重试后只保留成功结果。每次尝试及原因必须进入记录。

## 可复现命令目标

主命令现已支持：

```powershell
uv run --no-sync python scripts/run_layout_acceptance.py --tier nightly --generated-profile
uv run --no-sync python scripts/run_layout_acceptance.py --tier release --generated-profile
uv run --no-sync python scripts/run_layout_acceptance.py --tier release --generated-profile --generated-only --shard-index 0 --shard-count 4
uv run --no-sync python scripts/run_layout_acceptance.py --tier release --generated-profile --generated-only --resume-from <checkpoint-dir>
```

E1因子、shard和resume已经进入该入口，并继续由 `scripts/merge_layout_acceptance.py` 合并证据。探索六包的统一编排使用 `scripts/run_layout_exploration.py`，两者共享相同报告/证据模型。

## 验收标准

- nightly和release所有静态 `VALID/INVALID` 预期满足；
- 150/300个仿真样本全部有完整阶段报告和3种子证据；
- 人员核算误差为0，所有指标有限；
- 串行与1/2/4 shard合并的canonical结果一致；
- 中断续跑不重复、不遗漏、不覆盖证据；
- 目标硬件预算通过，或以具体瓶颈和测量证据进入review；
- 运行证据清楚记录dirty worktree，不把不可复现环境标为release证据。

## 退出条件

代码实现的退出条件已经满足：档位、E1因子、分片、merge、resume、环境manifest、RSS/tracemalloc与四重场景浸泡均有自动化。完整执行的退出条件仍是v2 nightly和release证据落盘并在声明硬件上冻结预算；在那之前必须继续标记 `larger simulation scale runs pending`。
