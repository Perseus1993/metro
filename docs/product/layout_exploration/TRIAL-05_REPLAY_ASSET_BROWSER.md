# PM-028-E5 回放、数字资产与真实浏览器试探包

- 优先级：P1
- 状态：`implemented / 36 of 36 Chromium runs passed / external binaries deferred to PM-029`
- 依赖：E1～E4稳定代表场景；ADR-008

## 要回答的问题

E5验证上游场景进入 `StationScene v1`、`asset_manifest.v1` 和 `ReplayPackage v2` 后，展示层是否按真实实体和拓扑渲染，而不是回退到固定站型或固定电梯数量；同时明确程序化资产和未来外部数字资产之间的支持边界。

## 当前合同事实

- `StationScene v1` 已包含楼层、物理实体、关系、编译拓扑和runtime binding；
- `asset_manifest.v1` 当前正式证据是按semantic kind生成程序化占位资产；
- renderer支持rect、polygon、polyline、point的点集归一化，并在scene render model中应用rect的 `rotation_deg`；
- 未知runtime/relation/asset引用会形成展示诊断；
- 外部GLB、纹理、单位换算、坐标轴、LOD和动画通道尚无完整版本化合同。

程序化资产、损坏引用、rect旋转和有限placement override现已进入正式门禁。外部二进制资产审计已形成“发布 `asset_manifest.v2`、v1不宣称整合”的版本决定，并进入PM-029。

## 实际结论（2026-07-18）

- B01～B12在1280×720、1600×1000、1920×1080共36次真实Chromium运行全部通过；
- 每个场景保存一张1600×1000主证据图；HTTP、page error、console error、画布、边界、楼层切换、0/1/3/6电梯和四时刻人数均有结构断言；
- 缺失binding在UI显示 `asset_binding_missing`，未知引用由合同拒绝或前端形成稳定诊断；
- `rect.rotation_deg`、point/polyline/polygon和 `fit_geometry + scale/rotation/offset` 已实现并测试；0电梯场景不再回退绘制固定电梯。

## 12个代表场景

| ID | 场景 | 主要风险 |
|---|---|---|
| `B01` | 单层、0电梯、稀疏资产 | 无跨层时不能残留固定电梯 |
| `B02` | 两层、1电梯、标准资产 | 最小跨层绑定 |
| `B03` | 两层、3电梯、密集资产 | 多物理实体与多runtime绑定 |
| `B04` | 三层、6电梯、镜像、密集资产 | 当前最大合法设施数量 |
| `B05` | L形足迹 | 凹多边形缩放与裁切 |
| `B06` | T形足迹 | 长轴关系线和楼层布局 |
| `B07` | 瓶颈站厅 | 窄颈、队列与资产覆盖 |
| `B08` | 相邻层接力连接 | 同一旅程跨多个物理设施 |
| `B09` | 进出闸机分离 | gate direction和关系可视性 |
| `B10` | 缺失/未知资产绑定副本 | 稳定诊断与程序化降级边界 |
| `B11` | polygon/polyline/point混合几何 | 非rect几何 |
| `B12` | 旋转rect和placement override | `VALID`：scene旋转后应用受约束placement变换 |

`B08` 已随E1的分段跨层决定进入 `VALID`，并纳入36次浏览器门禁。

## 三种视口

- 1280 × 720：常见笔记本；
- 1600 × 1000：当前自动化基线；
- 1920 × 1080：大屏检查。

基础浏览器运行数：`12 × 3 = 36`。移动端不在当前专业桌面工具范围内，除非产品方向改变。

## 四个检查时刻

对有旅客场景检查：

1. `loaded`：回放包加载完成；
2. `first_active`：首名旅客出现；
3. `peak`：站内人数或队列达到本次运行峰值；
4. `final`：完成或right-censored终点。

不是所有36次运行都保存四张金图。每个场景保留1600×1000的一个主证据图；其他时刻和视口只保存结构摘要，失败时保存完整截图。

## 场景与运行绑定断言

- 页面楼层标签数等于 `station_scene.levels`；
- 可见物理实体按 `scene_entity_id` 唯一，数量与scene一致；
- 每个runtime ID只映射一个scene entity；
- 一部电梯拥有上/下行等多个runtime时仍只绘制一个物理实体；
- 回放事件和旅客状态使用runtime binding，不解析字符串ID猜owner；
- scene relation的两端均存在；未知端点产生稳定诊断；
- 缺少 `replay_package` 的旧包只走明确的compatibility fallback，并在UI显示兼容模式。

## 资产门禁：当前v1

`VALID`：

- 每个scene entity有且只有一个默认程序化asset binding；
- asset ID唯一、binding ID唯一；
- binding引用存在的asset和scene entity；
- 不支持的semantic kind使用程序化占位外观，不得消失；
- AssetManifest和ReplayPackage往返指纹稳定；
- 资产变化不改变station topology或simulation metrics。

`INVALID`：

- binding引用未知asset；
- binding引用未知scene entity；
- 重复asset/binding ID；
- manifest/replay semantic fingerprint篡改；
- 非本地simulation/visualization pointer。

`B10` 要分别验证两种行为：合同构造阶段的未知引用应拒绝；已进入前端的缺失binding应显示 `asset_binding_missing` 诊断。两者不能混成一个含糊的fallback。

## 外部数字资产审计

在引入GLB/纹理前先形成资产合同决策，至少定义：

- `asset_kind`和受支持格式；
- 内容URI、内容hash和版本；
- 米制单位、up轴、front轴和原点；
- 包围盒、锚点、默认scale/rotation/offset；
- semantic kind兼容性；
- LOD选择和缺失LOD策略；
- 动画channel名称、循环和时间基准；
- 纹理、材质、透明和色彩空间；
- 许可证、来源和可分发性；
- 加载失败、hash不符和超预算时的fallback。

当前决定是发布新的 `asset_manifest.v2`，而不是把URI/hash/坐标轴等长期塞进v1未约束metadata。ADR-008已更新；PM-029负责合同评审与后续导入实现。在此之前外部资产仍是 `proposed / not implemented`，v1只承诺程序化fallback。

## 几何和placement审计

- polygon：顶点顺序、闭合策略和凹多边形；
- polyline：至少两个有限点、线宽展示策略；
- point：可见最小尺寸与命中区域；
- rect rotation：renderer应用 `rotation_deg`，并验证旋转后边界；
- placement override：`fit_geometry` 后按scale、rotation、offset应用有限变换，非法参数原子化诊断并拒绝该override；
- 跨楼层实体：一物理连接器在多个level的显示方式。

旋转和placement已按上述规则实现并测试；门禁继续禁止静默忽略或画成未旋转矩形。

## 真实浏览器断言

每次运行必须检查：

- HTTP资源全部成功或命中声明的fallback；
- 无page error和console error；
- scene render model非空且diagnostics符合预期；
- Canvas有非透明像素；
- 所有实体像素包围盒与画布相交，关键设施不得完全裁出画布；
- 楼层切换后只显示应属于该层或跨层的实体；
- 0/1/3/6电梯数量来自scene，不出现固定数量；
- 峰值和终点时旅客数量与trace摘要一致；
- 1280×720下关键状态和诊断可见且不遮挡主画布。

不使用整页像素逐点golden作为主要门禁。结构断言、实体包围盒、诊断和少量人工可读截图共同构成证据。

## 性能观察

记录每个视口的DOMContentLoaded、scene model构建、首帧、峰值帧和截图耗时，以及实体/关系/轨迹点数量。首轮只建立基线；后续同硬件同浏览器版本回归超过20%进入review，不直接与不同机器比较。

## 退出条件

- 36次基础浏览器运行满足各自预期；
- 12个主证据图和机器结构摘要可复现；
- 当前v1的所有损坏引用正确拒绝或诊断；
- rect rotation和placement override有明确支持/拒绝决定；
- 外部资产合同形成版本化决策及后续实施项；
- 文档继续区分“程序化fallback可用”和“外部数字资产已整合”。
