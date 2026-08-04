# Alignment 数据集清单

| dataset_id | 来源 | License | 引用 | 大小 | 状态 |
|---|---|---|---|---|---|
| eindhoven_platform_v1 | https://zenodo.org/records/13784588 | CC-BY-4.0 | Pouw et al. 2024；10.5281/zenodo.13784588 | raw 862,133,833 B；canonical 185,234,516 行（days 01–10） | active；已构建并计算指标 |
| julich_corridor_stub | https://ped.fz-juelich.de/database | 研究使用请注明数据来源 | 10.34735/ped.da | 未选择实验条目 | pending；无真实文件/几何，不计完成 |
| atc_osaka_stub | https://dil.atr.jp/crest2010_HRI/ATC_dataset/ | 研究用途 | Brščić et al., IEEE THMS 2013 | 未选择日期文件 | pending；无真实文件，不计完成 |

Eindhoven 当前只使用公开包的 days 01–10 文件，不把其余 50 天写成已下载或已验证。
Jülich 与 ATC 的 pending 状态会让下载/构建入口显式失败；不会生成空成功 artifact。
