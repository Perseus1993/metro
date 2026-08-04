# 10 Anvari et al. (2015)

## 证据状态

- 状态：`full_text_verified`
- 书目核验：Bani Anvari, Michael G. H. Bell, Aruna Sivakumar, Washington Y. Ochieng. “Modelling shared space users via rule-based social force model.” *Transportation Research Part C: Emerging Technologies* 51, 83–103 (2015). DOI: [10.1016/j.trc.2014.10.012](https://doi.org/10.1016/j.trc.2014.10.012)。
- 开放全文：[UCL Discovery 记录](https://discovery.ucl.ac.uk/id/eprint/10042206/) 标注为 Author Accepted Manuscript。
- 本地文件：[`../papers/10_anvari_et_al_2015_rule_based_social_force.pdf`](../papers/10_anvari_et_al_2015_rule_based_social_force.pdf)
- PDF 核验：PDF 1.5，32 页，未加密；首页题名与四位作者一致，末页参考文献完整可渲染。SHA-256：`034760CE7644A5CECAD1D4078C4DC24CC626E6FCD25D106ACA5E294E5B6019C3`。

## 原文直接结论

- 作者指出纯 SFM 难以单独解决全局导航与车辆运动约束，且实现中可能出现重叠或负速度，需要额外元素处理（第 3、5 节）。
- 提出的三层模型是：
  1. trajectory planning：用 flood-fill 距离图和中间目标规划绕开静态障碍的最短路径；
  2. force-based modelling：扩展 SFM，统一生成行人与汽车轨迹，并加入不同交互对的作用项；
  3. rule-based constraints：处理车辆转向/速度约束、预测冲突和最小改变量的避碰规则（第 4–7 节）。
- 路径层将平面划为 15 cm × 15 cm 单元，使用 Manhattan 与 Chessboard 组合的 Variant-2 距离图；再用障碍相交检查删除不必要的中间目标（第 5.2–5.3 节）。
- 异质主体不是只改一个速度参数：汽车使用椭圆几何、不同视野/交互、跟驰项、转向角约束和基于 closest point of approach 的冲突处理；行人—汽车交互另有力项（第 6–7 节）。
- 校准使用 Brighton New Road 一小时视频提取的轨迹、速度和加速度，对 pedestrian–pedestrian、pedestrian–car、car–pedestrian、car–car 四类交互分别拟合强度 A 与范围 B；随后比较真实与模拟轨迹/速度分布（第 8 节）。

## 对本项目的解释（项目推论，不是原文结论）

- 这篇论文最有价值的是“导航场/中间目标 → 连续动力学 → 补充规则”的工程结构，证明 SFM 之外保留规则层并不破坏学术合法性。
- 对地铁项目可迁移的是组件接口，而不是道路参数：不同主体可共享仿真循环，但轮椅、推车、行李乘客、工作人员或机器人应拥有自己的几何、运动能力、感知和冲突规则。
- 它还提醒我们，全局路线和局部避障是两个不同问题；局部墙体排斥不能替代拓扑路径或可达性规划。

## 局限与不能据此声称的内容

- 场景是行人—汽车共享街道，不是地铁站；没有站内活动链、闸机、扶梯、排队、站台或列车门过程。
- 作者明确将安全评价排除在本文范围之外；高密度 stop-and-go/振荡、更多主体类别、几何影响和“system optimal”指标仍列为未来工作（第 9 节）。
- 校准来自单一地点和一小时视频，文化、天气、道路布局、交通构成与密度均可能影响外部有效性。
- 文中主要展示校准后轨迹和速度分布接近；不能把它解读为已经完成跨地点、独立留出集或地铁场景验证。
- 15 cm 网格、8.9 m/s 车辆限速以及 A/B 参数均是该道路模型的设计/校准选择，不能直接移植到站内。

## 可检验的项目要求

1. 架构测试应能独立替换路径/导航、连续运动和规则约束组件，并记录每次规则覆盖动力学输出的原因。
2. 静态障碍测试：只靠局部排斥与加入中间目标/导航场两种方案应可对比，后者必须避免局部绕障失败和不必要折点。
3. 异质主体契约应显式包含几何尺寸、速度/加速度/转向能力、感知范围和适用规则；不能只用 `agent_type` 加一个速度倍率。
4. 冲突规则应以可观测条件触发，并测试最小间距、time-to-closest-approach、速度改变量和轨迹连续性。
5. 不同交互对的参数必须分别校准并给出数据覆盖；道路论文中的数值不得成为地铁默认值。

## 理论分级建议

**B+：强工程架构与异质主体先例，不是地铁站理论根基。** 它可作为“为何需要 SFM 外的导航层和规则层”的直接证据。
