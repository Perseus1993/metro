# PM-033 P1 Evidence

- 生成时间 (UTC): 2026-08-03T11:59:17.416989+00:00
- 环境: Python 3.12.13; Torch 2.13.0+cu126; CUDA 12.6; device NVIDIA GeForce RTX 3080
- 决策: **STOP**
- 原因: Throughput gate failed: 32×300 does not meet P0 80% lower bound.

## 门控汇总
- 场景门: PASS
- 梯度门: PASS
- Metro boundary smoke: PASS
- 32×300 吞吐门: FAIL

## 关键指标
- 块级总判: PASS
- 自动/黑箱 p50 最小比值: 0.41
- 达到最优比值预算: 4
- 吞吐 32×300: 615963.067885321 (P0 baseline: 997550.1830075786)
- 吞吐比: 0.6174757705203502
- 文献留出基线通过: FAIL

## 场景矩阵
| 场景 | 结果 | 关键指标 |
| --- | --- | --- |
| M1_single_walker | PASS | endpoint_error_m=0.07750988006591797; minimum_agent_gap_m=n/a; minimum_wall_clearance_m=1.8266665935516357; max_speed_mps=1.1999995708465576; projection_contacts=0 |
| M2_head_on | PASS | destination_error_m=0.059303853660821915; minimum_agent_gap_m=0.13976192474365234; minimum_wall_clearance_m=1.5991365909576416; max_speed_mps=1.1999881267547607; projection_contacts=0 |
| M3_bidirectional_corridor | PASS | mean_abs_progress_m=5.811266899108887; minimum_agent_gap_m=0.09009948372840881; minimum_wall_clearance_m=0.3407468795776367; max_speed_mps=1.5682917833328247; projection_contacts=0 |
| M4_bottleneck | PASS | agents_past_bottleneck=19; minimum_agent_gap_m=0.008764714002609253; minimum_wall_clearance_m=0.08905297517776489; max_speed_mps=1.8000001907348633; projection_contacts=0 |
| M5_slot_reuse | PASS | slot_reused=True; velocity_reset=True; active_ids_match=True |
| M6_level_isolation | PASS | first_agent_delta_m=0.0 |
| M7_dynamic_obstacle | PASS | final_x_m=7.280649662017822; minimum_agent_gap_m=n/a; minimum_wall_clearance_m=2.8266665935516357; max_speed_mps=1.1649566888809204; projection_contacts=0; minimum_agent_gap_m_after_obstacle=n/a; minimum_wall_clearance_m_after_obstacle=0.3717387318611145; max_speed_mps_after_obstacle=1.1995757818222046; projection_contacts_after_obstacle=0 |
| P1-02_polygon_walkable_50 | PASS | requested_agents=50; spawned_agents=50; invalid_starts=0; minimum_agent_gap_m=0.014432817697525024; minimum_wall_clearance_m=0.10972309112548828; max_speed_mps=1.7999999523162842; projection_contacts=6 |
| P1-02_geometry_refresh_tick | PASS | pass_rate=True; minimum_agent_gap_m=n/a; minimum_wall_clearance_m=0.8298344016075134; max_speed_mps=1.1997039318084717; projection_contacts=0 |

## 合成4参数预算-误差（P1-03 / P1-04）
| Budget | Autograd p50 | Black-box p50 | Autograd/Black-box |
| --- | ---: | ---: | ---: |
| 2 | 0.505342960357666 | 0.502022922039032 | 1.0066133201750016 |
| 4 | 0.48387330770492554 | 1.1814945936203003 | 0.4095433955582103 |

## P1-05：JuPedSim 伪观测拟合
- Seed: 17
- Budget: 120
- 基线损失: 0.41615
- 拟合后损失: 4.0618
- 模型族差距: 0.689
- 宏观差异: 1.84

## P1-06：真实数据留出（Holdout）
| Budget | 数据集 | Train loss | Holdout loss | Holdout/Train | Relative error |
| --- | --- | ---: | ---: | ---: | ---: |
| 20 | synthetic-protocol-juelich-stub | 0.715811 | 3.3784 | 0.00307 | 0.607 |
| 40 | synthetic-protocol-juelich-stub | 0.715811 | 3.3784 | 0.00307 | 0.607 |

## 吞吐（P1-07）
| Device | Batch | Slots | Agent-step/s | Peak MiB |
| --- | ---: | ---: | ---: | ---: |
| cpu | 1 | 300 | 14,561 | — |
| cuda | 1 | 300 | 26,797 | 4.5 |
| cuda | 8 | 300 | 212,567 | 36.1 |
| cuda | 32 | 300 | 615,963 | 140.9 |
| cuda | 1 | 1024 | 92,589 | 52.1 |

## P1-08：论文骨架
- 研究主张：在离散运营边界约束下，可微行人仿真内核在保持吞吐路径可维护的前提下，是否能以更少预算恢复参数并获得可外推的真实场景校准？
- 图表（优先级）:
  - 图1: P1-01/P1-02 blockers 结果（M1~M7 + 多边形薄切片）
  - 图2: 合成多参数预算-误差曲线（autograd vs black-box p50/p95）
  - 图3: 训练-留出轨迹误差与宏观指标对比
  - 图4: 吞吐回归（CPU + CUDA；32×300）
  - 图5: 失败样本与边界条件列表
- 相关工作定位：
  - 可微 ABM（AgentTorch/GradABM）在模型域上，尚未覆盖离散设施边界的行人内核标定。
  - 对比参数搜索基线（MassMotion/Viswalk 思路）强调可解释性强但预算代价高。

- 关联条件检查: 对应门控: 块级可行性、合成预算优势、真实留出验收、吞吐回归。
