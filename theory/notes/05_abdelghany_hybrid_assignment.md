# 05 - Abdelghany, Abdelghany & Mahmassani (2016): A hybrid simulation-assignment modeling framework for crowd dynamics in large-scale pedestrian facilities

## 核验结论

- 证据状态：`metadata_verified`
- 推荐分级：`B+ - 大规模可扩展性依据`
- “圣杯”判断：它为“网络分配 + 高分辨率局部运动”的耦合提供同行评议先例，但全文未取得，当前只能作为架构方向背书，不能作为实现细节来源。
- 全文状态：未发现合法开放全文。作者机构页提供元数据/摘要，IDEAS/RePEc 明示出版社全文仅供 ScienceDirect 订阅者。未绕过付费墙。
- 证据基础：下列“直接结论”仅来自作者机构记录和正式摘要。

## 书目信息

- 作者：Ahmed Abdelghany; Khaled Abdelghany; Hani Mahmassani
- 年份：2016
- 期刊：Transportation Research Part A: Policy and Practice, 86, 159-176
- DOI：10.1016/j.tra.2016.02.011
- 作者机构记录：<https://portfolio.erau.edu/en/publications/a-hybrid-simulation-assignment-modeling-framework-for-crowd-dynam/>
- DOI 入口：<https://doi.org/10.1016/j.tra.2016.02.011>
- 访问状态核验：<https://ideas.repec.org/a/eee/transa/v86y2016icp159-176.html>
- 核验日期：2026-08-02

## 研究问题与方法（摘要级）

论文针对大规模行人设施中“捕捉集体拥堵”与“计算可扩展性”的权衡，组合动态 simulation-assignment 逻辑与两层/双分辨率设施表示。

## 原文直接支持的结论（摘要级）

1. 顶层是设施网络，用于路线规划和活动过程中的选择。
2. 底层是在所有开放空间上的高分辨率 Cellular Automata，用于局部机动和运动决策。
3. 模型应用于麦加 Al-Haram Al-Sharif Mosque 地面层的朝觐人群；摘要称其能表现观察到的拥堵现象。
4. 论文明确把精细拥堵表达与大设施可扩展性作为主要设计权衡。

## 对本项目的解释

- 该文支持把全站网络分配/活动规划与高分辨率局部运动解耦，并建立一致的信息交换。
- 它可以作为未来大型换乘枢纽扩展的学术先例，但不能仅凭摘要推导“只在局部区域开启微观仿真”或具体切换算法。
- 本项目若仍对所有开放空间运行连续社会力，借用的只是分层分配思想，不是论文底层 CA 的复现。

## 适用边界与不得过度声称

- 全文、算法细节、校准流程、计算规模和误差指标未核验。
- 摘要中的底层明确是 CA；不能写成该文验证了社会力或当前 Unity 运动器。
- 案例是单个大型宗教设施地面层；不能直接外推多层地铁、列车过程或多站联合仿真。
- “准确表现拥堵”是摘要中的作者结论，当前没有足够全文证据量化准确度。

## 可检验要求

1. 网络层与微观层交换时必须守恒人数、活动状态和时间，不能生成或丢失乘客。
2. 用逐步放大的人数、面积和拓扑规模做性能基准，同时报告拥堵图/旅行时间误差。
3. 分层结果需与全高分辨率基线对照，证明加速没有改变关键路径份额和瓶颈指标。
4. 若引入区域级分辨率切换，必须另找全文方法依据并测试边界处的轨迹连续性；不能把它归功于尚未核验的本文细节。
5. 取得合法全文后再核对 dynamic assignment 的迭代、收敛与校准要求。

