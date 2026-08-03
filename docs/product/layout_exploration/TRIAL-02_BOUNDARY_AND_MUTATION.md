# PM-028-E2 临界值与故意破坏试探包

- 优先级：P0
- 状态：`implemented / 227 deterministic cases passed`
- 依赖：E1生成器基本稳定；现有schema、布局规则和诊断码

## 实际结论（2026-07-18）

227个A～G组确定性案例全部符合预先声明的通过/拒绝结果；数值有限性、长度/ID、旋转、容量、足迹、跨层相交、队列、端口和引用诊断已经闭合，目录中不再遗留 `AUDIT`。

## 要回答的问题

随机场景通常远离边界，容易漏掉浮点容差、极限尺寸、非法数值和错误引用。E2用确定性 `-ε / 等于 / +ε` 案例验证：合法边界是否稳定通过，非法边界是否在正确阶段以稳定诊断拒绝。

## 原则

- 每个案例只改变一个主要变量，保持首个失败原因可归因。
- 几何长度使用 `ε = 0.001m`，面积使用 `ε² = 0.001m²`；另加一组 `1e-9` 浮点噪声探针，不把它当现实测量精度。
- 边界“等于”是否包含由当前代码合同决定，例如尺寸和0.5m净距当前均为闭区间。
- 容量、单位、非有限数和浮点容差均已形成明确的 `VALID/INVALID` 合同；以下“初始审计”文字保留试探缘由，最终分类以机器目录为准。

## 案例组A：组件净距与重叠

当前规则：最小净距 `0.5m`；允许重叠面积容差 `0.01m²`。

| 案例 | 取值 | 预期 |
|---|---:|---|
| `CLEARANCE-BELOW` | 0.499m | `INVALID`，`layout.component_clearance_too_small` |
| `CLEARANCE-EXACT` | 0.500m | `VALID` |
| `CLEARANCE-ABOVE` | 0.501m | `VALID` |
| `CLEARANCE-NOISE-LOW` | 0.5m - 1e-9 | `INVALID`，按严格0.5m闭区间处理 |
| `OVERLAP-BELOW` | 0.009m² | 按当前容差应不报overlap；仍需检查净距规则 |
| `OVERLAP-EXACT` | 0.010m² | 按当前 `>` 规则不报overlap；记录是否符合产品意图 |
| `OVERLAP-ABOVE` | 0.011m² | `INVALID`，`layout.components_overlap` |

该组至少对gate/elevator、elevator/stairs、shop/equipment和queue/facility四类对象重复，避免只验证一种Shapely形状关系。

## 案例组B：足迹与跨层相交

当前普通设施足迹容差为 `0.25m`；跨层设施要求其形状与每个声明连接楼层相交。

| 案例 | 取值 | 预期 |
|---|---:|---|
| `FOOTPRINT-IN` | 边界内0.001m | `VALID` |
| `FOOTPRINT-EXACT` | 恰在原始边界上 | `VALID` |
| `FOOTPRINT-TOL-EXACT` | 超出0.250m | `VALID`，同时记录Shapely buffer边界行为 |
| `FOOTPRINT-TOL-OUT` | 超出0.251m | `INVALID`，`layout.component_outside_level_footprint` |
| `VERTICAL-TOUCH` | 连接器只接触某层足迹边界 | `VALID`；产品合同接受边界接触，稳定使用 `intersects` 语义 |
| `VERTICAL-MISS` | 与某连接层间隔0.001m | `INVALID`，`layout.vertical_connector_misses_level` |

队列对足迹使用同一0.25m缓冲，需独立跑 `QUEUE-TOL-EXACT/OUT`，不能由设施案例代替。

## 案例组C：尺寸上下界

对每种有尺寸合同的设施生成 `min-ε / min / max / max+ε` 四例：

| kind | width范围(m) | height范围(m) |
|---|---:|---:|
| entrance | 1～12 | 1～12 |
| gate | 4～30 | 1.5～10 |
| escalator | 2～20 | 4～30 |
| stairs | 3～20 | 4～30 |
| elevator | 3～15 | 3～15 |
| platform_edge | 1～120 | 0.5～8 |
| shop/service_room | 2～50 | 2～30 |
| equipment | 1～40 | 1～20 |
| obstacle | 0.5～60 | 0.5～60 |

为控制案例数，每个kind先用宽度测四点、用高度测四点；另选gate、elevator、platform_edge做宽高同时处于四个角点的组合。预期诊断为 `layout.component_width_out_of_range` 或 `layout.component_height_out_of_range`。

## 案例组D：队列合同

队列服务点到owner的最大距离为 `max(2.0m, spacing_m × 2.5)`。

- spacing为0.8m时测试1.999m、2.000m、2.001m；
- spacing为1.2m时测试2.999m、3.000m、3.001m；
- owner与queue楼层不一致；
- owner不存在；
- queue在足迹外；
- 两队列覆盖；
- queue覆盖唯一窄颈或独立设施；
- capacity为0、-1和极大整数；spacing为0、负值和非有限数。

前五类及容量、spacing非法值均已有明确诊断或质量门禁；非法容量和非正/非有限spacing稳定拒绝。

## 案例组E：设计约束

对当前约束逐项检查：

- 楼层数：0、1、3、4；4层必须作为 `INVALID`，不能偷偷提升 `max_levels=3`；
- 层高：2.999m、3m、12m、12.001m；
- 最大深度：27.999m、28m、28.001m；
- 画布：120m × 80m边界内、边界上和越界；
- 网格：0.5m对齐和偏离1mm均进入机器目录；当前合同不强制网格对齐，偏移保持 `VALID`；
- 单位：`meters`、未知单位和空单位；
- schema：当前版本、未知未来版本、空版本；
- 元素kind：允许枚举、未知枚举；
- 楼层order/elevation重复或矛盾。

若schema只完成反序列化但没有拒绝错误约束，报告必须写成合同缺口，不得把“Python能构造对象”当作支持。

## 案例组F：引用和标识破坏

在现有5类负向语料上扩展：

- 重复level、element、queue、connection、port、scene entity、runtime binding和asset binding ID；
- connection引用未知element或未知port；
- queue引用未知owner；
- connector引用未知level；
- runtime binding引用未知scene entity；
- asset binding引用未知asset或未知scene entity；
- 同一runtime ID出现两次；
- semantic fingerprint被篡改；
- 本地JSON pointer改为外部路径或非法pointer。

每类只声明一个最早失败阶段和一个主要诊断码，避免不同层重复报错导致测试脆弱。

## 案例组G：非有限数与极端值

对坐标、宽高、旋转、层高、容量、队列间距和服务率注入：

- `NaN`；
- `Infinity` / `-Infinity`；
- `-0.0`；
- 极大有限数；
- 超长ID和空ID。

非有限数必须在合同或布局阶段拒绝，不允许流入Shapely、语义指纹JSON、仿真或Canvas。`-0.0` 按有限零值接受，规范化往返和指纹必须稳定。

## 计划规模与分层

初始目录为227例，按上述枚举计算：

| 组 | 计划数 | 计算方式 |
|---|---:|---|
| A 净距与重叠 | 28 | 7个边界值 × 4类对象关系 |
| B 足迹与跨层 | 8 | 6个设施案例 + 2个队列足迹案例 |
| C 尺寸上下界 | 92 | 10种kind × 8个单轴边界 + 3种关键kind × 4个宽高角点 |
| D 队列合同 | 17 | 6个服务距离 + 11个owner/足迹/覆盖/容量/spacing案例 |
| E 设计约束 | 26 | 楼层、层高、深度、画布、网格、单位、schema、kind和order |
| F 引用与标识 | 19 | 重复ID、未知引用、指纹和JSON pointer |
| G 非有限数与极值 | 37 | 7类数值字段 × 5种注入 + 2个ID边界 |
| 合计 | 227 | `28 + 8 + 92 + 17 + 26 + 19 + 37` |

数值字段七类固定为：坐标、宽高尺寸、旋转角、层高、队列容量、队列间距和运行设施服务率。G组虽然跨设计与运行合同，仍以同一注入目录管理。

分层执行：

- smoke：每组至少一个合法、一个非法，共20～25例；
- nightly：完整案例目录；
- release：完整目录 + 1e-9噪声 + JSON/fingerprint篡改复跑。

实现时必须由案例目录自动核对227这个计划数。合同评审导致增删时，先升级计划版本并更新上表；不得让文档与机器目录静默漂移。

## 验收标准

- 所有 `VALID` 在适用阶段通过；
- 所有 `INVALID` 在声明阶段拒绝并命中预期主要诊断码；
- 同一案例重复100次，首个失败阶段和主要诊断码一致；
- 无非有限数进入场景、回放或仿真证据；
- 诊断包含case ID、路径、实际值和允许范围；
- 目录不遗留 `AUDIT`；每个原审计项已有支持或拒绝决定，不能以“当前没报错”自动转成支持；
- 失败最小化后仍命中相同首个阶段和主要诊断码。

## 退出条件

完整机器可读案例目录落地；精确案例数、通过数、拒绝数和审计决定可复现；所有P0数据完整性缺口关闭后，E3才可进入正式运行。
