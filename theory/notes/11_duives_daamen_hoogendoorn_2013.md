# 11 Duives, Daamen & Hoogendoorn (2013)

## 证据状态

- 状态：`metadata_verified`
- 证据范围：出版社/机构元数据与摘要；未取得可合法下载的对应 17 页期刊全文。
- 书目核验：Dorine C. Duives, Winnie Daamen, Serge P. Hoogendoorn. “State-of-the-art crowd motion simulation models.” *Transportation Research Part C: Emerging Technologies* 37, 193–209 (2013). DOI: [10.1016/j.trc.2013.02.005](https://doi.org/10.1016/j.trc.2013.02.005)。
- 机构元数据：[TU Delft Research Portal](https://research.tudelft.nl/en/publications/state-of-the-art-crowd-motion-simulation-models/)。出版社入口：[ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0968090X13000351)。
- 全文处理：未保留 PDF。检索到的 TU Delft 文件实际是 265 页博士论文，其中一章声明为该文的“adapted and updated version”；它不是 17 页期刊论文，已从 `papers/` 移除。

## 原文可以直接支持什么

以下仅由摘要支持：

- 论文的目标是把既有行人仿真模型与已知 crowd phenomena 对照，判断低密度条件下开发的模型能否用于高密度人群，并识别研究空白。
- 它是广泛但非穷尽的综述，讨论 cellular automata、social force、velocity-based、continuum、hybrid、behavioral 和 network models。
- 摘要把模型粗分为“较慢但较精细的微观模型”和“较快但行为可信度存疑的宏观模型”，并指出精度与速度兼顾的实际应用仍不充分。
- 作者主张用于 crowd simulation 的模型应能再现所列 crowd phenomena 中的大部分；这为建立现象级验收矩阵提供了综述依据。

## 对本项目的解释（项目推论，不是原文结论）

- 本文适合作为“模型验收不能只看小人是否到达终点，而要看集体涌现与高密度行为”的审查背书。
- 它不提供一个可直接实现的新算法；更适合转化为验证目录、模型覆盖矩阵和速度—精度权衡说明。
- 清单列出的 lane formation、arching、bottleneck oscillation、stop-and-go waves 等具体项目，在获得原文前应视为待逐项核验，不能把二手清单当作全文证据。

## 局限与不能据此声称的内容

- 无期刊全文，无法核验完整现象清单、每一类模型的对照表、评价标准和作者对单个模型的具体判定。
- 2013 年的 state of the art 不能代表 2026 年所有新模型；它是历史性评估框架，不是当前覆盖度的充分综述。
- “某模型理论上能复现某现象”不等于本项目的具体实现已经复现；仍需本地场景、指标和容差验证。
- 博士论文章节虽可作为后续补充阅读，但因其已改编更新，不能用于声称“期刊原文第 X 页/表 Y”。

## 可检验的项目要求

1. 在代码优化前先建立 `phenomenon → 场景几何 → 输入条件 → 观测量 → 通过阈值 → 证据来源` 的验证矩阵。
2. 性能测试与行为测试分开：既报告计算吞吐/规模，也报告轨迹、速度—密度、流量、队列和集体现象是否合理。
3. 每个声称“支持”的现象必须绑定可重复实验与量化判据，不能以动画截图代替。
4. 在获取全文前，具体 crowd phenomena 列表标记为 `provisional`；全文核验后再决定哪些成为强制验收项。

## 理论分级建议

**A2（暂定）：局部动力学验收与模型覆盖的核心综述背书，但不是算法“圣杯”。** 因全文缺失，细节引用需降级，不能承担唯一验证依据。
