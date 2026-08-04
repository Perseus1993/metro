# 仿真站点火灾视觉样例

这是 `apps/station_unity_replay` 的独立实验副本，用于观察真实两层站布局中的火焰与疏散跑动效果。

## 打开方式

1. 用 Unity 6000.3.18f1 打开本目录。
2. 打开 `Assets/Scenes/MetroReplay.unity`。
3. 点击 Play。

样例从回放约 84 秒处开始，在约 145 秒处循环。居民位置、朝向和疏散路线来自冻结的 `Assets/StreamingAssets/replay.json`；火焰只是视觉叠加，不参与路径计算，也不构成新的仿真证据。

正式工程 `D:/metro/apps/station_unity_replay` 未被修改。
