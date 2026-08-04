# 08 Robin, Antonini, Bierlaire & Cruz (2009)

## 证据状态

- 状态：`metadata_verified`
- 证据范围：出版社摘要；未获得可合法下载且与期刊论文书目完全一致的全文。
- 书目核验：Thomas Robin, Gianluca Antonini, Michel Bierlaire, Javier Cruz. “Specification, estimation and validation of a pedestrian walking behavior model.” *Transportation Research Part B: Methodological* 43(1), 36–56 (2009). DOI: [10.1016/j.trb.2008.06.010](https://doi.org/10.1016/j.trb.2008.06.010)。
- 出版社入口：[ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0191261508000763)。
- 全文处理：未下载。EPFL 可公开获取一份 2007 年同名技术报告，但作者包含 Sabina Schneider 而非 Javier Cruz，且载体、年份和作者序不同，故不作为这篇期刊论文的全文替代。

## 原文可以直接支持什么

以下仅由摘要支持：

- 作者提出并验证了一个基于离散选择的行人步行行为模型，将行为分为不受他人约束的模式和受约束模式。
- 受约束行为由 leader–follower 与 collision avoidance 两部分表达；空间备选项之间的相关性由 cross-nested logit 捕捉。
- 模型通过最大似然法在真实行人轨迹数据上估计；轨迹由视频人工跟踪获得。
- 作者使用 TU Delft 控制实验采集的双向流数据进行验证。

## 对本项目的解释（项目推论，不是原文结论）

- 它最适合充当“行为模型必须经历 specification → estimation → validation”的程序性背书。
- 若本项目继续保留社会力作为操作层，本文仍可约束校准纪律：参数不能凭观感填写，必须说明数据、估计目标和独立验证场景。
- 若 DCM 被放到 tactical layer，数据也必须换成路径/设施选择数据；操作层轨迹数据不能单独识别闸机、楼梯或扶梯的效用系数。

## 局限与不能据此声称的内容

- 无全文，无法核验训练/验证样本量、候选集细节、效用函数、参数显著性、交叉验证协议、具体预测指标及哪些子行为验证较弱。
- 摘要称验证成功，但不能仅据此声称模型已在地铁站、拥挤高密度、不同文化或复杂设施条件下验证。
- 该模型仍是 walking behavior 模型，不能替代活动调度、站内路线选择或设施过程模型。

## 可检验的项目要求

1. 校准报告必须将 specification、estimation、validation 分成可审计步骤，并保存数据版本、参数置信信息与预测指标。
2. 验证集应与估计集分离；至少加入双向流等交互场景，而非只复现用于拟合的轨迹。
3. 评估应分别报告方向、速度、碰撞/最小间距等结果，避免用一个总误差掩盖局部失败。
4. leader–follower 和 collision avoidance 若在实现中存在，应有可区分的触发条件与场景测试。

## 理论分级建议

**B+：校准与验证规范的强背书。** 它不是总体站内仿真理论，也不是 tactical route choice 的直接参数来源；在取得全文前不宜把细节写成确定事实。
