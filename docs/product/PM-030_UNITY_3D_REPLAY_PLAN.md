# PM-030 Unity 三维回放实施计划

## 1. 产品决定

- 形态：真 3D 回放，不采用仅有高度分层的 2.5D 贴图方案。
- 职责边界：Python 仿真是唯一事实源；Unity 不重新计算路径、排队、设施服务或上下车结果。
- 输入：面向 Unity 的精简 JSON；保留 `replay_package.v2`、`station_scene.v1`、`simulation_trace.v1`、清场审计和路由决策证据，不携带浏览器专用 `visual_tracks`。
- 默认目标：可靠读取两层站的 50 人高保真完整清场结果，以 1 秒权威仿真快照回放到最终剩余 0 人；100/300 人完整结果保留为容量与压力测试。

### Unity Windows 程序范围锁定

- 唯一默认主流程：打开程序即播放 `clearance_50_complete.replay.json`，从 0 秒、50 人开始，直到 253 秒、剩余 0 人。
- 默认观察重点：已离场人数、剩余人数、清场进度与完成状态。
- 场景完整性：列车、电梯、扶梯、楼梯、闸机、屏蔽门和站台设施全部默认可见；它们服务于清场空间理解，不能因功能收口而被隐藏。
- 非目标：默认程序不证明列车班次、到发或上下客运营结果。清场合同没有列车到站事件时，列车只能标记为静态环境展示。
- 可信边界：Unity 动画是 Python 结果的展示，不替代仿真日志、清场审计或现场安全结论。

## 2. 从初级到全体

| 级别 | 交付 | 验收门槛 | 当前状态 |
|---|---|---|---|
| L0 合同层 | Python 直接导出 JSON；Unity 严格校验 schema、ID 和楼层引用 | 真实 Python 文件可读取；错误合同明确失败 | 已完成 |
| L1 基础三维 | 楼层、入口、闸机、站台门、障碍物的程序化占位资产 | 两层站和主要设施正确生成 | 已完成 |
| L2 时间轴 | 播放、暂停、0.5x–8x、任意跳转、键盘快捷键 | 跳转前后同一时刻结果一致 | 已完成 |
| L3 跨层服务 | 依据服务事件重建扶梯、楼梯、电梯中的乘客位置 | 可从任意时刻恢复进梯、运行、到达状态 | 已完成 |
| L4 规模验收 | 320 对象预热池、Windows Player；50 人默认验收和 100/300 人容量压力测试 | 默认 50 人平均 FPS ≥ 30；压力样本不改变事实源 | 已完成 |
| L5 数字资产替换 | 用授权 Prefab 替换程序化入口/闸机/电梯/扶梯 | 语义绑定不变，合同和回放逻辑不改 | 后续美术迭代 |
| L6 全体站型 | 三层站、换乘站、多站模板、资产清单 v2 | 每种站型有固定回归样例和性能基线 | 后续扩展 |

## 3. 技术结构

```text
Python Mesa + JuPedSim + versioned evacuation router
    -> simulation_trace.v1（1 秒乘客快照、设施服务事件、路由决策日志）
    -> station_scene.v1（楼层、几何、实体、运行时绑定）
    -> Unity 精简 replay JSON（剔除浏览器表现轨迹）
    -> Unity 合同读取器
    -> 无状态 ReplaySampler
    -> 程序化 StationSceneBuilder + PassengerPool
    -> Windows 三维回放
```

Unity 的随机跳转不依赖上一次播放状态：每次都由“目标时间 + 前后快照 + 当前设施服务事件”直接计算位置。电梯使用 `board_end_time` 到 `arrive_time` 重建垂直运动，扶梯和楼梯使用完整服务区间插值。

## 4. 首版验收映射

| 要求 | 证据 |
|---|---|
| 成功读取一个两层站 Python 结果 | 真实 `clearance_50_complete.replay.json` 载入，清场审计为 50/50 完成、剩余 0 |
| 正确生成楼层和主要设施 | 程序化楼板、入口、闸机、站台门、障碍物、扶梯、电梯、楼梯 |
| 播放、暂停、倍速、任意跳转 | `ReplayClock` 和 UI；EditMode 自动测试 |
| 正确跨楼层、进电梯、上下扶梯 | Python 长场景含电梯、扶梯、楼梯服务事件；`ReplaySampler` 无状态重建 |
| 50 人高保真完整清场 | 1 秒权威快照；路由插件和决策数可追溯；初始帧 50 人；最终帧 0 人；RTX 3080 / D3D12 Player 报告 |

## 5. 数字资产策略

首版不依赖外部付费资产，所有设施使用可替换的程序化占位体。后续数字资产只通过语义种类绑定：`entrance`、`gate`、`platform_edge`、`escalator`、`elevator`、`stairs`、`obstacle`。这样更换模型、材质或 LOD 不会改 Python 合同或回放算法。

外部资产进入项目之前必须记录来源、许可证、版本、面数、纹理尺寸和 LOD；不把来源不明的模型直接打进验收版本。

B1 站厅的实景依据、国家标准分级、可执行美术参数和同机位验收规则见
`PM-031_B1_CONCOURSE_VISUAL_PROTOCOL.md`。

## 6. 自动执行入口

```powershell
& 'D:\metro\apps\station_unity_replay\scripts\test.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\build.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\acceptance.ps1'
& 'D:\metro\apps\station_unity_replay\scripts\run.ps1'
```
