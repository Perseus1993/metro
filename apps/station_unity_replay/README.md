# Metro Station 50 人清场回放

Unity 6.3 LTS 的 50 人高保真完整清场演示端。Python 仿真仍是唯一事实源；Unity 只读取 `visualization_bundle.v1` / `replay_package.v2` / `station_scene.v1` / `simulation_trace.v1` 的纯 JSON，不在 Unity 内重新计算乘客行为。

双击 Windows 程序的默认主流程是：初始 50 人、持续疏散、最终剩余 0 人。100/300 人版本继续保留为容量与压力测试样本。列车、电梯、扶梯、楼梯、闸机和屏蔽门等主要资产全部默认显示；其中列车在清场合同没有到站事件时作为静态环境展示，不作为运营或清场结论证据。

电梯只由场景合同中的物理实体 `element:elevator_a` 生成。B1 装修层不会再额外摆放一台与回放坐标无关的样板电梯，避免人群轨迹穿过重复模型。

## 首版能力

- 从 Python 回放合同生成多层楼板、入口、闸机、站台门、障碍物、扶梯、电梯与楼梯。
- 基于仿真快照插值乘客位置；设施服务事件负责重建进出电梯、上下扶梯和跨层过程。
- 默认回放以 1 秒间隔导出权威 Mesa/JuPedSim 快照，比原 5 秒回放减少转角切线和穿模；Unity JSON 不再携带浏览器使用的平滑 `visual_tracks`。
- 疏散路径显式通过版本化 `metro.shortest_path@1.0.0` 路由端口生成，并把每次路由决策写入 `simulation_trace.routing_decision_logs`；可用 `--routing-plugin-manifest` 替换为通过合同验证的本地算法。
- 时间轴是无状态采样，支持播放、暂停、0.5x–8x 和任意时间跳转。
- 乘客对象池预热 320 个对象，避免正常 300 人回放过程反复实例化。
- 外观层异步加载 Kenney 与 Poly Haven 的 CC0 设施模型；长椅、垃圾桶、顶灯、
  摄像头、灭火器、绿植、门框和服务设施不会反向影响 Python 仿真结果。
- 默认播放 Python 的 50 人完整清场结果；最后一帧必须为 0 人。
  `clearance_300_complete.replay.json` 与 `two_level_300_full.replay.json` 保留为拥堵复现和 GPU 压力测试数据。
- EditMode 合同/时间轴/跨层/默认 50 人测试，以及 Windows Player 性能验收报告。

第三方外观资产的来源、许可与哈希记录见
`Assets/StreamingAssets/Decor/THIRD_PARTY_ASSETS.md`。

## 自动化入口

仓库根目录执行：

```powershell
& 'D:\metro\apps\station_unity_replay\scripts\test.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\generate-clearance-50-replay.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\build.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\acceptance.ps1'
```

打开可视化回放：

```powershell
& 'D:\metro\apps\station_unity_replay\scripts\run.ps1'
```

需要调试历史列车运营回放时，显式传入运营回放；该入口不属于默认清场证据：

```powershell
& 'D:\metro\apps\station_unity_replay\Builds\Windows\MetroStation3DReplay.exe' `
  --replay-json 'D:\metro\output\unity_replay\train_service_demo.replay.json' `
  --platform-hero
```

需要单独观察 GPU 压力样本时，显式传入
`D:\metro\output\unity_replay\two_level_300_full.replay.json`。

Player 也接受 `--replay-json <path>`；环境变量 `METRO_REPLAY_JSON` 是第二优先级输入。
需要近景验收某个设施时，可追加 `--camera-entity <scene_entity_id>`，不影响回放数据。
