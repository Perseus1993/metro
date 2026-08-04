# Theory 元老院索引

更新时间：2026-08-02

## 一句话结论

没有一篇论文能单独充当整套系统的“圣杯”。当前最稳的理论主链是：

1. **Daamen (2004)**：站内旅客流建模的领域总纲；
2. **Kneidl et al. (2013)**：图导航、局部导航与微观运动的分层架构蓝图；
3. **Nishida et al. (2023)**：从实测选择、参数估计到端到端相似度验证的可执行范例；
4. **Tordeux et al. (2015)**：当前默认 `CollisionFreeSpeed` 运动模型的直接理论血缘。

Hoogendoorn & Bovy (2004) 是战略/战术行为理论的重要母体，但当前只能按元数据和摘要引用；它不能独自为操作层、上下车过程或本站参数背书。

## 阅读入口

- [元老院宪法](CONSTITUTION.md)
- [现行法典](LAWS.md)
- [立法章程](SENATE_CHARTER.md)
- [理论分级与“圣杯”判断](reports/THEORY_HIERARCHY.md)
- [理论—生产问题立法研究](reports/THEORY_TO_CODE_MATRIX.md)
- [现有设计立法调研](reports/CODE_DESIGN_AUDIT.md)
- [凯撒治国计划：权威文献评价](reports/CAESAR_PLAN_AUTHORITY_REVIEW.md)
- [Theory 工作区验收记录](reports/QA_LOG.md)
- [统一文献台账](sources/library.csv)
- [老师原始清单的规范化转录](sources/TEACHER_LIST.md)
- [检索与证据规则](sources/SEARCH_PROTOCOL.md)

## 当前取证状态

- 老师清单：16 篇题录全部独立核验。
- 合法全文：9 篇；其余 7 篇只保留元数据/摘要证据，不放置伪全文或来源不明副本。
- 代码反查补充：1 篇，即当前默认运动模型直接来源 Tordeux et al. (2015)。
- 本地 PDF 合计：10 份，均记录版本、页数、来源和 SHA-256。
- 逐篇证据卡：17 张，位于 `notes/`。

## 使用边界

`theory/` 只颁布法律并保存立法材料，不参与包发现、运行时导入、配置装载或参数读取。校准、测试、执法、工程实现和发布验收全部在 Theory 之外完成。
