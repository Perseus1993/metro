# PM-028 生成布局与回放拓扑验收证据

- 日期：2026-07-18
- 对应需求：PM-028
- 当前结论：`exploration implemented / E1-E5 pass / generator-v2 smoke+shard+resume+soak pass / v2 nightly-release pending`
- 安全边界：这是软件工程与可复现性证据，不是现场校准、客流容量证明或疏散安全认证。

## 用户与结果

- 用户：站型设计者、仿真研究者和回放检查者。
- 问题：上游新增楼层、入口、闸机或多部电梯后，下游可能仍依赖固定站型和固定设施数量。
- 结果：同一版本化 recipe 能重建设计，设计必须通过几何、拓扑、队列、运行设施映射和资产解析门禁，并可抽样进入既有微观仿真与运营故障验收。

## 已实现

1. `layout_recipe.v1` 与 `scenario_corpus.v1`：记录生成器版本、seed、站型骨架、楼层数、入口/闸机/电梯数量、楼梯/扶梯组合、镜像、资产密度、运营工况，以及v2生成器的footprint/vertical/fare拓扑因子。
2. 约束式生成：复用正式黄金模板骨架，受控生成 1～3 层、1～4 个入口、1～2 组闸机和多层站 1～6 部电梯；生成后重新派生队列、端口和连接。
3. 合理性门禁：正式设计/拓扑校验之外，检查跨层图连通、队列互不覆盖、队列不遮挡实体、服务设施队列完整、无图编译诊断、无 walkable fallback 和 JSON 往返稳定。
4. 回放门禁：每个设计重新编译 `StationScene v1` 与 `asset_manifest.v1`，检查物理实体唯一、运行设施全部绑定、资产引用全部解析、楼层和电梯数量来自场景数据。
5. 负向语料：重复元素、未知队列 owner、队列越界、连接未知楼层和站台断连均返回预期稳定诊断码。
6. 分层仿真抽样：生成设计可直接传入既有正常/出站/换乘/疏散旅程和五类运营工况，不要求注册为固定模板；抽样按站型、运营工况、电梯数量和资产密度保持多样性。
7. 失败证据：成功场景只保存 corpus recipe；失败场景额外保存 recipe、验收记录和可重现设计，避免提交数千个重复快照。
8. PM-028探索：E1拓扑、E2临界值、E3需求—故障、E4变形敏感性、E5真实浏览器、E6分片/续跑/浸泡统一使用版本化案例和阶段报告。

## 验收档位

| 档位 | 静态场景 | 仿真抽样 | 固定种子 |
|---|---:|---:|---|
| smoke | 64 | 12 | 42 |
| nightly | 2,000 | 150 | 41、42、43 |
| release | 10,000 | 300 | 41、42、43 |

完整仿真只运行分层样本；全部场景均运行静态几何、拓扑、回放和资产绑定门禁。

## 已执行证据

- 2026-07-18统一探索运行：E1 64/64、E2 227/227、E3 252/252、E4 150/150、E5 36/36、E6 scale摘要2/2与soak 8/8；统一证据目录为 `output/layout_exploration/pm028-full-20260718-v2`。
- generator v2 fresh smoke：64/64静态和12/12仿真通过；静态wall time 23.99秒、traced peak 1.70MB、最终RSS 139.55MB；证据目录为 `output/layout_exploration/pm028-e6-smoke-v2`，manifest明确记录dirty worktree。
- 同一64案例v2语料按1、2、4 shard实际重跑后的canonical fingerprint一致；CLI两分片合并、强制中断和逐案例续跑通过。
- 4类重场景各执行2次浸泡；人员核算误差0、相对wall/peak memory回归不超过20%、无子进程泄漏。

- 256 个生成 recipe：设计/拓扑/队列门禁全部通过，256 个设计指纹均唯一。
- 早期generator v1 nightly静态档位2,000个场景：全部通过设计、拓扑、队列、回放和资产绑定门禁，失败0、设计唯一率100%；当前工作站串行耗时约216秒。楼层分布为1层500、2层1,000、3层500；这不替代v2完整档位。
- 自动化语料测试：128 个场景覆盖 1、2、3 层和 0～6 部电梯，全部通过质量门禁。
- 三层、镜像、双闸机、四入口、六部电梯、密集资产场景：物理电梯数为 6，运行时电梯绑定按真实编译结果生成；JavaScript 展示模型无诊断。真实 Chromium 页面动态显示三层标签、画布非空，且无 page error 或 console error。
- 可视证据：`output/generated_layout_qa/three_level_six_elevators.png`。
- 负向语料 5 类：全部返回预期诊断码。
- 生成场景已使用确定性移动后端进入既有四旅程验收并验证重复运行指纹一致。
- 完整 smoke 仿真抽样 12 个场景：全部通过四旅程、确定性复跑和对应运营工况；五类运营 profile 均被覆盖，当前工作站串行耗时约 33 秒。
- 仓库主全量回归：578 tests、1,454 subtests 全部通过；新增 Chromium 展示测试随后单独通过，生成布局针对性测试合计 11 项通过；12 项 Import Linter 架构合同全部保持。

## 可复现命令

静态 smoke：

```bash
uv run --no-sync python scripts/run_layout_acceptance.py \
  --tier smoke \
  --generated-count 64 \
  --generated-simulation-samples 0
```

完整 smoke 档位：

```bash
uv run --no-sync python scripts/run_layout_acceptance.py \
  --tier smoke \
  --generated-profile
```

针对性自动化：

```bash
uv run --no-sync pytest -q \
  tests/test_generated_layout_acceptance.py \
  tests/test_scene_render_model.py \
  tests/test_replay_scene_contracts.py
```

## 尚未声明完成

- 已在当前工作站执行早期generator v1的2,000场景nightly静态门禁；尚未执行generator v2 nightly的2,000静态+150仿真，也未执行v2 release的10,000静态+300仿真，因此没有宣称v2完整档位时长预算通过。
- 浏览器可视诊断、逐层过滤、rect旋转和有限placement override已完成；外部二进制资产不属于v1，已拆分为PM-029 / `asset_manifest.v2`。
- 当前程序化资产只证明实体不会因缺少美术资源而消失，不证明 3D 美术质量。

## 布局拓扑探索实施

2026-07-18 已将详细方案及实际结论落盘到 [`layout_exploration/README.md`](layout_exploration/README.md)，包括：

1. 拓扑形态；
2. 临界值与故意破坏；
3. 需求—故障耦合；
4. 变形等价与测试敏感性；
5. 回放、数字资产与真实浏览器；
6. 规模、分片与浸泡。

六包的案例、验收器、CLI和自动化已实现。E1～E5与E6 smoke/分片/续跑/浸泡已测试；只有generator v2完整nightly/release规模运行和PM-029外部资产仍保持pending。
