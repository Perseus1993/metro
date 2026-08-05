# Alignment engineering-debt register

Established in Round 25. This register records mechanisms or scenario choices that may hide an
unresolved failure mode. A normal review may only remove or narrow entries. Adding or broadening
an entry requires retiring another entry in the same review; otherwise the review must explicitly
report and justify the net increase.

Round 25 is the baseline-registration review. Round 24 exposed six unclassified risk candidates;
the current review leaves zero of those candidates unclassified and also records two newly exposed
risks instead of hiding them. The resulting baseline is five registered debts and three
evidence-backed legitimate designs. Because Round 24 had no comparable register,
`registered_debt_delta` is not defined for this first registration; it must not be represented as a
negative number. The comparable backlog measure is `unclassified_candidate_delta = -6`. No
Round-25 production change is claimed to have erased pre-existing debt merely by classifying it.

| id | what | masks | introduced | justification | retire_evidence | expiry_round |
|---|---|---|---|---|---|---|
| `DEBT-1` | `platform_boarding` shifts the alighting-source lattice laterally by 10 m. | A source/boarding geometry that may overlap or be infeasible when based on the unshifted train-door geometry. | `8d31e11f`, Round 23 carry-over | The offset made the diagnostic scene runnable, but no observed passenger emergence-position dataset or engineering rule supports the value 10 m. | Replace the constant with line/vehicle observation data (including uncertainty), then pass source preflight and a held-out multi-seed trajectory comparison without an arbitrary translation. | 26 |
| `DEBT-2` | Stalled region approaches invoke strategic replanning. | Persistent release-region or route-geometry stalls can be converted into apparent progress rather than removed at their source. | `29af5cf2`, pre-Round-25 carry-over | Rerouting is a valid congestion response in pedestrian models, but the frozen 900-step artifact records 618 triggers for 784 spawned passengers (78.8%), far above the 1% occasional-recovery threshold. | Remove the underlying stall cause and show `passenger_replanned_stalled_region_approach / spawned_persons <= 1%` across the frozen 240/600/900 ladder and seeds 42/43/44, with source integrity and liveness gates still passing. | 26 |
| `DEBT-3` | The frozen synthetic `platform_boarding` design uses seven parallel boarding doors. | Extra service portals may compensate for an unmeasured boarding bottleneck and overstate the represented rolling stock's usable interface. | uncommitted design atop `0b938dcd`, Round 24 frozen into Round 25 | Seven doors produced real boarding progress, so Round 25 correctly froze it instead of retuning; however, no vehicle/line observation is linked to the count or spacing. | Link a line- and rolling-stock-specific observed door count/spacing dataset and validate the mapping, or explicitly reclassify the scene as synthetic and add a separate observation-matched design. | 27 |
| `DEBT-4` | The nominal exit-gate service envelope and observed completed throughput differ by about 19×. | Source-integrity success can be mistaken for evidence that the downstream gate/route service chain is physically calibrated. | `55543e2b` evidence baseline, re-registered Round 25 | Admission ownership is deliberately narrower than downstream throughput calibration, so the gap does not block T2; leaving it implicit would overstate what T3/T5 prove. | Attribute travel, queue, service-ready, release-blocked, and completion time across the frozen 600/900 ladder and reconcile observed service with `3 × 55 persons/min`, or replace that nominal parameter with a calibrated value and held-out evidence. | 26 |
| `DEBT-5` | Physical placement backpressure relies on retry, while waiting-capacity retry and stalled-platform parking lack stable per-mechanism counters in Round-25 artifacts. | Frequent retry can turn persistent release-apron or waiting-region contention into eventual throughput and obscure normal-path dependence. | pre-Round-25 placement behavior, made explicit by T6 | T5 records 16 placement blocks / 138 spawned people (11.59%); T8 records 21 / 156 (13.46%), both above the 1% occasional-recovery threshold. The events remain visible and admission-arm histograms are identical, but the frequency is debt, not success. | Add stable counters for placement, waiting-capacity retry, and stalled-platform parking; demonstrate each trigger ratio <=1% across 240/600/900 and seeds 42/43/44, or remove the underlying contention while retaining source-integrity and liveness gates. | 26 |

## Candidate triage

| candidate | decision | basis |
|---|---|---|
| `alighting_source_lateral_offset_m = 10.0` | `debt` → `DEBT-1` | The repository exposes it as a free scene parameter and consumes it in source-certificate placement, but carries no observation or specification for 10 m. |
| `passenger_replanned_stalled_region_approach` | `debt` → `DEBT-2` | The frozen artifact reports 618 triggers / 784 spawned people. Rerouting can be a legitimate congestion response, but this frequency is normal-path dependence rather than occasional recovery. See the [MERL congestion-aware pedestrian routing paper](https://www.merl.com/publications/TR2023-099). |
| `jupedsim_recovered_agents` / `jupedsim_degraded_holds` counters | `legitimate_design` | These counters preserve, rather than suppress, runtime failure visibility and are release-gated at zero. Runtime measurements are a standard observability signal; see [OpenTelemetry Metrics](https://opentelemetry.io/docs/concepts/signals/metrics/). This judgment covers the counters, not any recovery mechanism they observe. |
| boarding doors 6 → 7 | `debt` → `DEBT-3` | The design is frozen and therefore not a Round-25 tuning knob, but the count and spacing lack external observational support. |
| `sandbox.metro_station_sandbox` compatibility surface | `legitimate_design` | All 111 Python modules in the production-overlap subtrees (`agents`, `calibration`, `compilation`, `design`, `facilities`, `migration`, `movement`, `planning`, `runtime`, `simulation_outputs`, `station`) are forwarding modules; the official package is forbidden from importing `sandbox`. Preserving a declared public compatibility surface during a release cycle is consistent with [Semantic Versioning's public-API compatibility contract](https://semver.org/). |
| Import Linter migration rule | `legitimate_design` | The repository uses forbidden-dependency contracts with `unmatched_ignore_imports_alerting = "error"`; exceptions require an ADR, owner, removal phase, and test and may only narrow. This is an enforceable boundary/retirement mechanism, consistent with [Import Linter contracts](https://import-linter.readthedocs.io/en/stable/). |
| nominal exit service vs completed-throughput gap | `debt` → `DEBT-4` | Independent sizing review recomputed `1400 / 74 = 18.9189`; admission credits do not alter downstream gate service or routing, so the gap remains unexplained. |
| high-frequency placement/waiting recovery | `debt` → `DEBT-5` | T5/T8 placement retry ratios are 11.59%/13.46%. Missing dedicated counts for waiting-capacity retry and stalled-platform parking are included in the retirement evidence instead of being treated as zero. |

## Review rule

Every `fix(...)` commit must state the user-visible failure mode, whether the change removes the
failure or only its visibility, and—if only visibility changes—the debt entry and retirement
evidence. `registered_debt_delta` is computed against this five-entry registered baseline only in
subsequent rounds; Round 25 reports it as not comparable.
