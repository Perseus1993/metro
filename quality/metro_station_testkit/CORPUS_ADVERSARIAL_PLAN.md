# 编译期校验器对抗语料实施与验收计划

- 负责人：Skull Breaker（斯科尔布雷克）
- 更新日期：2026-08-04
- 状态：`capacity_extension / verified`
- 范围：`quality/metro_station_testkit` 新测试资产；不修改生产校验器判定

## 1. 目标与边界

目标不是“登记诊断字符串”，而是证明当前编译器的 **46 个诊断契约**均有可执行反例，并覆盖所有真实 `issue/_issue` 发射点。当前生产源码共有 46 个 distinct diagnostic codes、50 个发射点和 20 个动态 producer；同一码可能由多个不同条件发射。

本次 capacity 扩展把 `packages/**` 固定为只读，只在 testkit 和专项测试中验收 `spatial_capacity.py` 引入的 14 个新诊断契约。`queues.capacity_not_materialized` 是该模块复用的既有契约，不计入 14；外围 exception boundary 的 `capacity.compile_failed` 另有 fault-injection probe。

本轮非目标：修改师兄的生产校验器、声明现实客流模型已校准、以正例全绿替代负例检出证据、为追求覆盖数字而绕过类型契约构造无意义对象。

## 2. 测试策略

每个 `CompilationNegativeCase` 是一组因果对：

1. `control`：合法输入，目标诊断不得出现，当前要求 control 完全无诊断。
2. `exercise`：只改变 `changed_fields` 声明的条件。
3. oracle：精确匹配 code 集合，并校验目标 `(severity, code, exact path)` 且目标只出现一次。
4. 同码多分支：每个 case 静态绑定自己的 emitter 行，运行时要求该 case 自己执行目标；动态诊断另追踪 20 个 producer origin。
5. `graph.compile_failed`、`holding.compile_failed`、portal compiler fallback：用受控 fault injection 验证异常到诊断的契约。

测试分层：

- `integration`：从真实 `StationDesignDocument` 进入公共编译入口。
- `component`：从有效编译产物只改一个字段，隔离密集复合判断。
- `fault_injection`：只验证 exception boundary，不把兜底分支伪称为设计空间中的“不可达”。

方法依据：

- Mutation-testing 思路用于设计 kill oracle：目标结果缺失或 code/severity/exact-path 被替换会在 mutant 侧失败，整个 decision 误报会在 control 侧失败。本轮不声称已覆盖每个复合表达式的原子条件取反。[Offutt 1992 coupling-effect research](https://doi.org/10.1145/125489.125473)
- MC/DC 思路用于同码分支和复合条件的单变量隔离：每个 probe 记录 `changed_fields`，不同 decision emitter 分开验收。[NASA/FAA MC/DC tutorial](https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20010057789.pdf)
- Metamorphic/property-based 思路用于后续平移、镜像、重排与阈值邻域扩展；本轮已实现确定性重放和生成语料 false-positive gate，不把它夸大成完整 property campaign。[Chen et al. metamorphic testing record](https://hdl.handle.net/1783.1/70576)、[Hypothesis official stateful testing docs](https://hypothesis.readthedocs.io/en/latest/stateful.html)

## 3. 分步验收指标

| 步骤 | 工作 | 验收指标 | 证据命令 | 当前结果 |
|---|---|---|---|---|
| 0 | 基线与边界确认 | 只修改 testkit/专项测试/本文档；生产校验器零改动；记录脏工作区 | `git diff -- quality/metro_station_testkit tests/test_compilation_code_coverage.py` | 已满足 |
| 1 | 自动 inventory | AST 不依赖单双引号；distinct code 与 emitter 分开；新增 code/site 无 case 时门禁红 | `pytest ...::test_01_inventory_matches_executable_case_registry` | 46 codes、50 emitters |
| 1b | Capacity 固定契约 | `spatial_capacity.py` 的 14 个新增契约写入显式集合；源码或 probe 任一侧悄悄删除均门禁红；不得用 `allowed_codes` 放宽 | `pytest ...::test_01b_spatial_capacity_extension_keeps_all_14_diagnostic_contracts` | 14/14 codes、17 branch probes |
| 2 | 补齐对抗因果对 | 46/46 code 至少一个 active probe；`blocked=0`；control 为空；mutant 精确命中 code 集合及目标 `(severity, code, exact path)` | `pytest ...::test_02_control_to_mutant_pair_kills_diagnostic_mutations` | 65 probes，全部 active |
| 3 | 发射与动态 producer 覆盖 | 每个 case 静态绑定并亲自执行目标；50/50 `issue/_issue` 与 20/20 动态 producer 行均覆盖；仍存在或新增但未执行的 site 报文件/函数/行。删除 site 由行为 probe 失败捕获，trace 不保留已删除源码的历史清单 | `pytest ...::test_03_every_concrete_emitter_site_is_executed_by_a_mutant` | emitters 50/50，producers 20/20 |
| 4 | 可重现性 | 每个 control/mutant 连续两次诊断 multiset 完全一致 | `pytest ...::test_04_cases_are_deterministic_and_reproducible` | 65/65 |
| 5 | 防误报正例门 | 固定 seed 的 32 recipe 默认门禁 0 error；release 前 256 recipe 0 error | `pytest ...::test_05_fast_generated_recipe_false_positive_gate`；设置 `METRO_RUN_256_RECIPE_PRECHECK=1` 后跑 test_06 | 32/32、256/256 均 0 error |
| 6 | 工程兼容 | ruff、pyright、专项 pytest、capacity 相关回归通过；确认本轮 `packages/**` 零写入 | 见第 5 节 | ruff/pyright/build 通过；专项 134 passed、1 skipped；capacity 回归 149 passed、1 skipped；相关 packages 源文件 hash 前后相同 |
| 7 | 独立审查 | 原 32-code 语料的质量/方法、metro 集成、通用性三类 agent 三轮复审 P0/P1=0；capacity 扩展继续服从同一 exact-oracle/site-binding 门禁 | agent 审查记录、步骤 1b–4 | 原语料复审完成；capacity 扩展 14/14 固定契约和 17/17 branch probes 验证通过 |

完成定义：步骤 1–7 全部满足；14 个新增 capacity 契约必须同时出现在固定集合、源码 inventory 和 executable probe 中；不能用 `blocked`、空 note 或固定数字替代可执行证据。

## 4. 当前覆盖矩阵

| 诊断码 | executable probes | 状态 |
|---|---:|---|
| `capacity.certificate_duplicate` | 1 | active |
| `capacity.certificate_empty` | 1 | active |
| `capacity.coactive_slot_conflict` | 1 | active |
| `capacity.compile_failed` | 1 | active |
| `capacity.demand_exceeds_storage` | 2 | active |
| `capacity.forecast_margin_low` | 1 | active |
| `capacity.internal_slot_conflict` | 1 | active |
| `capacity.policy_mismatch` | 1 | active |
| `capacity.slot_outside_certificate_domain` | 1 | active |
| `corridors.outside_walkable_area` | 1 | active |
| `geometry.detour_ratio_exceeded` | 1 | active |
| `geometry.entrance_platform_unreachable` | 1 | active |
| `geometry.level_domain_disconnected` | 2 | active |
| `geometry.walk_edge_not_traversable` | 5 | active |
| `graph.compile_failed` | 1 | active |
| `graph.enter_path_missing` | 1 | active |
| `graph.exit_path_missing` | 1 | active |
| `graph.unreachable_node` | 1 | active |
| `holding.capacity_below_required` | 1 | active |
| `holding.capacity_empty` | 1 | active |
| `platform.capacity_below_required` | 2 | active |
| `portals.binding_identity_mismatch` | 1 | active |
| `portals.clearance_too_small` | 1 | active |
| `portals.duplicate_binding_id` | 2 | active |
| `portals.duplicate_facility_id` | 1 | active |
| `portals.facade_mismatch` | 1 | active |
| `portals.level_mismatch` | 2 | active |
| `portals.missing` | 4 | active |
| `portals.outside_walkable_area` | 3 | active |
| `portals.same_side` | 1 | active |
| `portals.variant_group_invalid` | 1 | active |
| `queues.capacity_not_materialized` | 2 | active |
| `queues.path_self_intersection` | 1 | active |
| `queues.rank_edge_not_traversable` | 1 | active |
| `queues.row_order_invalid` | 1 | active |
| `queues.service_rank_invalid` | 1 | active |
| `queues.slot_clearance_conflict` | 3 | active |
| `queues.slot_detached_from_entry` | 1 | active |
| `queues.slot_outside_region` | 1 | active |
| `queues.slot_outside_safe_core` | 1 | active |
| `queues.slot_overlap` | 1 | active |
| `queues.slot_projection_mismatch` | 1 | active |
| `queues.topology_missing` | 2 | active |
| `release.batch_not_placeable` | 1 | active |
| `release.capacity_not_materialized` | 2 | active |
| `release.route_not_traversable` | 1 | active |

合计：46/46 diagnostic codes，65 executable probes，0 blocked，0 unreachable；其中 14 个 spatial-capacity 新契约由 17 个 branch probes 覆盖，额外 probe 用于拆开重复发射条件和动态 producer guard。

## 5. 最终验证命令

```powershell
uv lock --check
uv run --no-sync ruff check quality/metro_station_testkit/src/metro_station_testkit/compilation_code_inventory.py quality/metro_station_testkit/src/metro_station_testkit/compilation_negative_cases.py tests/test_compilation_code_coverage.py
uv run --no-sync pyright quality/metro_station_testkit/src/metro_station_testkit/compilation_code_inventory.py quality/metro_station_testkit/src/metro_station_testkit/compilation_negative_cases.py tests/test_compilation_code_coverage.py
uv run --no-sync pytest tests/test_compilation_code_coverage.py -q
uv run --no-sync pytest tests/test_spatial_capacity_certificates.py tests/test_capacity_convergence_acceptance.py tests/test_compilation_code_coverage.py -q
$env:METRO_RUN_256_RECIPE_PRECHECK = "1"
uv run --no-sync pytest tests/test_compilation_code_coverage.py::test_06_256_recipe_pre_topology_extension_smoke_gate -q
uv run --no-sync pytest tests/test_geometry_reachability_validation.py tests/test_facility_portal_binding.py tests/test_compilation_code_coverage.py -q
```

仓库级 `lint-imports` 与全量 pytest 也要运行；如果被工作区既有问题阻断，必须记录具体既有违规和专项验证结果，不得静默跳过。

## 6. 后续增强（不计入本轮 46/46 完成数字）

- 用 mutation engine 对 50 个 emitter 与 20 个动态 producer 做 delete-emission、invert-guard、threshold、code/severity/path substitution 的真实 campaign；非等价 mutant kill rate 目标 100%。
- 对 `topology_missing`、`slot_projection_mismatch`、`facade_mismatch` 的复合 guard 建完整 MC/DC 条件对。
- 用 Hypothesis 对 portal/queue typed binding 做至少 200 examples/族的阈值邻域与 shrink；保存最小 seed。
- 对有效设计做平移、镜像、元素重排、alpha-renaming metamorphic invariants，path 按 ID 映射比较。
