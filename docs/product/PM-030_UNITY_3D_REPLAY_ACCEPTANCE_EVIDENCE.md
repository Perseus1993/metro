# PM-030 Unity 三维回放首版验收证据

## 结论

首版验收通过。Unity 6.3 LTS Windows Player 成功读取真实 Python 两层站完整清场结果，生成楼层和主要设施，支持时间轴控制与任意跳转，能依据设施事件重建电梯、扶梯和楼梯跨层过程，并在 RTX 3080 上稳定回放 300 人 120 秒。Python 清场审计为 300/300 完成、剩余 0 人，Unity 最后一帧也为 0 人。

## 被测对象

- Unity：`6000.3.18f1 (5ebeb53e4c07)`
- Player：`apps/station_unity_replay/Builds/Windows/MetroStation3DReplay.exe`
- 默认 Python 回放：`output/unity_replay/clearance_300_complete.replay.json`，93.02 MB
- 压力测试回放：`output/unity_replay/two_level_300_full.replay.json`，仅保留用于 300 人同时显示测试，不作为清场证据
- 场景：2 层、62 个实体、251 个 Unity 去重时间帧
- 清场：1255 秒，300/300 完成，剩余 0 人，最后一帧 0 人
- 服务证据：576 个设施事件，其中电梯 4、扶梯 223、楼梯 49、出站闸机 300
- 性能设备：NVIDIA GeForce RTX 3080，Direct3D 12，报告显存 20253 MB

## 验收结果

| 检查项 | 结果 | 证据 |
|---|---:|---|
| 读取两层站 Python 结果 | 通过 | 2 层、62 实体，合同版本校验通过 |
| 生成楼层和主要设施 | 通过 | 入口、闸机、站台门、障碍物、扶梯、电梯、楼梯均生成 |
| 播放、暂停、倍速、跳转 | 通过 | `ReplayClock` 自动测试与 Windows Player UI |
| 任意跳转结果一致 | 通过 | 无状态 `ReplaySampler` 电梯跳转回归测试 |
| 电梯与扶梯服务 | 通过 | Python 完整回放含 4 个电梯、223 个扶梯和 49 个楼梯事件 |
| Python 完整清场 | 通过 | `cleared=true`，完成 300/300，剩余 0，清场时间 1255 秒 |
| Unity 最后一帧清空 | 通过 | `zero_passengers_in_final_frame=true`，最后一帧可见人数 0 |
| 300 人稳定 120 秒 | 通过 | 最大/最小可见人数均为 300 |
| 性能 | 通过 | 平均 59.99 FPS，1% low 59.78 FPS，目标 ≥ 30 FPS |
| 运行时应用异常 | 通过 | Player 日志中应用异常匹配数为 0 |

## 自动测试

- Python：`tests/test_replay_json_export.py`、`tests/test_replay_scene_contracts.py`，2 passed。
- Unity 全量 EditMode（2026-08-01 全资产版本）：259/259 passed；默认范围回归 3/3 passed，覆盖默认 0 秒、列车可见、电梯渲染器可见、300/300 完成与最终 0 人。
- Windows GPU soak：7199 帧 / 120.009743 秒；300 人、清场、HDRP、写实人物与性能检查均为 `true`。

机器上的 D3D12 日志有一条“无法查询 info queue interface”的驱动调试接口提示；设备随后正常初始化为 RTX 3080，120 秒运行和截图均成功，未产生 Unity 应用异常。

## 证据文件

- 运行原始报告：`apps/station_unity_replay/Artifacts/runtime-acceptance.json`
- Unity 测试结果：`apps/station_unity_replay/Artifacts/metroreplay-clearance-results.xml`
- GPU 运行日志：`apps/station_unity_replay/Artifacts/runtime-acceptance.log`
- 电梯时刻截图：`apps/station_unity_replay/Artifacts/elevator-frame.png`

## 2026-08-01 默认产品收口回归

- 双击 Player 默认载入 `clearance_300_complete.replay.json`，从 0 秒开始；列车和全部垂直交通设施默认生成。
- 默认 UI 只突出已离场、剩余人数、清场进度和完成状态。
- 开场镜头对准 B2 的 300 人主力人群；主力人群换到 B1 后，镜头切换到装修后的出口闸机端。
- 清场合同没有列车到站段时，列车保持停靠展示并明确归类为环境资产，不冒充运营事件。
- Windows 最终状态短验收再次得到 `complete_clearance_source=true`、`all_passengers_completed=true`、`zero_passengers_in_final_frame=true`、清场时间 1255 秒。

新增证据：

- 全量 EditMode：`apps/station_unity_replay/Builds/Evidence/MetroReplay_AllEditMode_20260801.xml`
- 默认 UI：`apps/station_unity_replay/Builds/Evidence/Clearance300_Default_UI.png`
- B1 出口人流：`apps/station_unity_replay/Builds/Evidence/Clearance300_ExitGate_B1_900s.png`
- 最终 0 人：`apps/station_unity_replay/Builds/Evidence/Clearance300_FinalStateAcceptance.json`

全资产显示回归：

- 全量 EditMode：`apps/station_unity_replay/Builds/Evidence/AllAssets_AllEditMode.xml`
- 默认 300 人＋列车＋B2 垂直交通：`apps/station_unity_replay/Builds/Evidence/AllAssets_Default_UI.png`
- 修复后默认 300 人＋列车＋权威电梯：`apps/station_unity_replay/Builds/Evidence/ElevatorFix_Default_AllAssets.png`
- B1 扶梯＋楼梯＋闸机＋人流（重复样板电梯已移除）：`apps/station_unity_replay/Builds/Evidence/ElevatorFix_B1_900s_v3.png`
- 唯一权威电梯近景：`apps/station_unity_replay/Builds/Evidence/ElevatorFix_Authoritative_200s.png`

电梯防穿模回归：场景中只保留 `element:elevator_a` 一个物理电梯根节点，并验证其根坐标来自 `station_scene.v1` 的首个楼层端点；B1 装修层不得创建 `AccessibleElevator_Complete` 副本。对应默认范围测试 3/3 通过，Windows Player 于 2026-08-01 20:06 重新打包。

## 2026-08-01 B1 闸机层右侧楼板回归

- 根因：楼层基础网格只有单面，从下方或斜侧自由镜头观察时被背面剔除，视觉上表现为闸机层右侧缺少地板。
- 修复：楼层基础改为 0.18 米封闭楼板，包含顶面、底面及四周侧面；仅改变表现网格，不添加碰撞体，也不改变可行走区域与清场路径。
- EditMode：`apps/station_unity_replay/Artifacts/b1-floor-results.xml`，42/42 passed，包含 B1、B2 楼板闭合与无碰撞体回归。
- 闸机层右侧截图：`apps/station_unity_replay/Builds/Evidence/B1_RightFloor_SlabFix_900s.png`
- 默认清场视角：`apps/station_unity_replay/Builds/Evidence/B1_RightFloor_DefaultView_900s.png`
- Windows Player 于 2026-08-01 20:49 重新打包。

## 2026-08-01 B1 闸机层双侧装修回归

- 根因：B1 同时存在左侧进站闸机和右侧出站闸机，旧的 hero 逻辑只按当前镜头精装其中一侧，却隐藏了全层的基础设施表现。
- 修复：楼板、墙面、吊顶格栅、灯带、照明和反射探针覆盖完整 B1 轮廓；进站、出站两组闸机均生成精装模型和对应导视。
- 另一侧保留：非主镜头一侧原有客服室、售票机、入口与装饰资产不再被误隐藏；闸机障碍占位和队列辅助线仍隐藏，避免与精装闸机重叠。
- 场景合同：以上对象全部属于表现层，不创建 Collider，不改变 300 人清场路径或设施事件。
- EditMode：`apps/station_unity_replay/Artifacts/b1-both-sides-results.xml`，260/260 passed。
- 左侧进站精装视角：`apps/station_unity_replay/Builds/Evidence/B1_BothSides_EntryHero_900s.png`
- 默认 300 人出站视角：`apps/station_unity_replay/Builds/Evidence/B1_BothSides_Default_900s.png`
- Windows Player 于 2026-08-01 21:09 重新打包。

## 2026-08-01 列车前排位置回归

- 根因：旧布局从站台门线先偏移到 B2 楼层外边界，再额外偏移 1.72 米，导致列车和轨道被推到站台结构后方。
- 修复：列车中心直接从权威站台门线向轨道侧偏移 1.72 米；车门与屏蔽门横向缝隙小于 0.35 米，列车回到站台界面的前排且仍位于轨道侧。
- 场景合同：只修正列车及轨道表现锚点，不改变乘客轨迹、站台门实体或清场事件。
- EditMode：`apps/station_unity_replay/Artifacts/train-front-row-results.xml`，260/260 passed。
- 默认 300 人视角：`apps/station_unity_replay/Builds/Evidence/TrainFrontRow_Default_0s.png`
- Windows Player 于 2026-08-01 21:59 重新打包。

## 2026-08-01 100 人高保真路径回放回归

- **事实边界**：Python Mesa / JuPedSim 是唯一运动事实源；Unity 只读取 `simulation_trace.snapshots` 和设施事件并插值展示，不根据画面重新寻路。浏览器专用 `visual_tracks` 已从 Unity 精简包剔除，避免出现第二套轨迹事实。
- **路由证据**：显式使用 `metro.shortest_path@1.0.0`，记录 200 次版本化路由决策；Unity 标题和验收报告均显示权威快照间隔与路由插件证据。
- **时间分辨率**：默认 tick / 快照间隔由 5 秒收紧到 1 秒；文件包含 360 个 Unity 去重帧，100/100 于 360 秒完成，最后一帧 0 人。
- **拥挤根因修复**：上游站厅目标不再让所有旅客精确汇聚到 `(55, 24)`，改为确定性的旅客级分散目标；该点的正常步行重复对由 19 降为 0。设施分配为扶梯 B 41、扶梯 A 38、楼梯 14、电梯 7；四条出站闸机分配为 26/25/25/24。
- **Unity 回归**：`MetroReplay.Tests.EditMode.dll` 44/44 passed。同次全量运行中 UnitySkills 插件自己的迁移幂等测试 217/218，未影响 MetroReplay 结果，故不把全工程写成全绿。
- **Windows Player**：RTX 3080 / D3D12 运行 10.00 秒、600 帧，平均 59.98 FPS、1% low 59.58 FPS；100 人可见、HDRP、32 mm 物理相机、三级 LOD、完整清场、1 秒权威快照及版本化路由证据均为 `true`。120 秒路径截图已生成；截图专用进程退出时出现原生崩溃码，因此截图只作为画面证据，不作为稳定性证据。
- **尚未校准**：1 秒样本清场 360 秒，2 秒敏感性样本 398 秒。当前结果是代码层可追溯的最高保真回放，不代表已经用现场轨迹/客流数据校准，也不能用于安全预测。

新增证据：

- 权威回放：`output/unity_replay/clearance_100_complete.replay.json`
- Unity 内嵌回放：`apps/station_unity_replay/Assets/StreamingAssets/replay.json`
- Player 验收：`apps/station_unity_replay/Artifacts/runtime-acceptance.json`
- Unity 测试：`apps/station_unity_replay/Artifacts/editmode-results.xml`
- 120 秒截图：`apps/station_unity_replay/Artifacts/high-fidelity-100-dispersed-at-120s.png`
- 2 秒敏感性样本：`output/unity_replay/timestep_validation/clearance_100_tick2.replay.json`

## 2026-08-01 50 人设施前置分流回归

- **用户可见问题**：旧 100 人回放在站台中央先聚成一团，再向垂直交通设施分流；减到 50 人不能作为算法修复证据。
- **上游根因**：`station_evacuation` 的 Goal Graph 要求所有疏散旅客先抵达单一 `vertical_decision` 区域才执行设施选择。旧样本第 37 秒最大 0.75 米连通团为 76 人，其中 56 人尚无设施承诺。
- **修复（已由后续物理路由实现取代）**：疏散 Journey 由各层可步行连通分量、真实垂直设施入口/出口和出站闸机组成；旅客只能在实际可到达的入口进入设施，服务完成后才切换楼层并继续疏散。当前位置不再被标记成虚构的垂直交通决策区域，Unity 仍不承担寻路或视觉散开。
- **50 人结果**：`metro.shortest_path@1.0.0` 记录 100 次路由决策；50/50 于 253 秒清场，最终 0 人。0、30、60、90、120 秒的最大 0.75 米连通团分别为 3、5、4、4、4 人；全程最坏为第 139 秒四条出站闸机前合计 18 人，每条 3～5 人，属于设施排队而非共同目标点重叠。
- **反证对照**：100 人用同一修复重跑后，未选择设施的 `vertical_decision` 人数同样为 0，清场由旧版 360 秒降到 286 秒；第 25 秒仍有 71 人在相邻垂直设施银行前汇流，说明 100 人拥挤主要是容量/共同通道现象，50 人默认并非隐藏仍存在的决策点 bug。
- **自动验证**：Python 目标图/清场/回放相关测试 21/21 passed；Unity 全量 EditMode 262/262 passed，其中 MetroReplay 44/44。
- **Windows Player**：50 人、1 秒权威快照、版本化路由、完整清场、最终 0 人、HDRP 和 50 人可见检查均为 `true`；RTX 3080 / D3D12 平均 59.98 FPS、1% low 59.48 FPS。
- **截图边界**：30 秒截图已生成；截图专用 Player 在保存后仍返回原生崩溃码，故只作为画面证据。独立验收 Player 正常退出，稳定性以验收报告为准。

新增证据：

- 50 人权威回放：`output/unity_replay/clearance_50_complete.replay.json`
- 30 秒画面：`apps/station_unity_replay/Artifacts/fifty-routed-at-30s.png`
- Player 验收：`apps/station_unity_replay/Artifacts/runtime-acceptance.json`
- 全量 Unity 测试：`apps/station_unity_replay/Artifacts/editmode-results.xml`

## 2026-08-01 列车—垂直交通净空回归

- 根因：跨层平面图使用不同的二维绘图原点；旧投影把上下层扶梯端点直接连线，导致梯段穿越轨行区。列车移回屏蔽门前排后，该错误更明显。
- 楼层配准：Unity 仅在表现坐标转换中用权威电梯竖井配准楼层；同一楼层的地板、设施、旅客、队列点和轨迹统一刚性平移。上游快照、事件时间、状态、距离差和清场结果均未修改。
- 列车标高：列车和轨道下沉 0.44 米至轨面，车门中心与屏蔽门竖向误差小于 0.03 米；横向门缝继续小于 0.35 米。
- 垂直设施：扶梯主梯段限制为约 30°，楼梯约 35°；上层权威锚点保留，展示路线的双向首尾仍精确落在上游端点。梯段不再进入列车包络。
- 专项 EditMode：`apps/station_unity_replay/Artifacts/vertical-single-flight-results.xml`，10/10 passed。
- 默认视角：`apps/station_unity_replay/Builds/Evidence/TrainEscalatorSingleFlight_Final_0s.png`
- Windows Player 于 2026-08-01 22:42 重新打包。
