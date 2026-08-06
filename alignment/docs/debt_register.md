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

Round 26 explicitly broadened the in-progress register from five to six entries by adding
`DEBT-6`. Round 25's exit admission capacity equalled the complete 240-step exit demand, so its
zero exhaustion ratio could not test whether the supposedly finite resource ever constrained
flow. The completed Round-26 service-chain work retires `DEBT-2` and `DEBT-5`; four entries remain
open. Relative to the five-entry Round-25 baseline, `registered_debt_delta = 4 - 5 = -1`.

Round 26 also renegotiates the four entries that were all originally due in Round 26. `DEBT-1`
is moved to Round 27 because retirement requires passenger-emergence observations or an explicit
synthetic-scene reclassification; runtime scheduling cannot produce that missing evidence.
`DEBT-2`, `DEBT-4`, and `DEBT-5` were retained as Round-26 service-chain work. `DEBT-2` and
`DEBT-5` now have their required multi-seed retirement evidence. `DEBT-4` moves to Round 27 because
the unchanged T7 criterion cannot yet be reconstructed from one measurement cohort. `DEBT-6`
also moves to Round 27: capacity 40 binds, but leaves 23 exit demands pending, while the formal
ten-minute sizing run fails closed at finite entry decision-holding capacity. These are explicit
one-round widenings, not silent expiry edits and not evidence that either unresolved mechanism is
acceptable. `DEBT-3` remains due in Round 27.

## Open debt

| id | what | masks | introduced | justification | retire_evidence | expiry_round |
|---|---|---|---|---|---|---|
| `DEBT-1` | `platform_boarding` shifts the alighting-source lattice laterally by 10 m. | A source/boarding geometry that may overlap or be infeasible when based on the unshifted train-door geometry. | `8d31e11f`, Round 23 carry-over | The offset made the diagnostic scene runnable, but no observed passenger emergence-position dataset or engineering rule supports the value 10 m. | Replace the constant with line/vehicle observation data (including uncertainty), then pass source preflight and a held-out multi-seed trajectory comparison without an arbitrary translation. | 27 |
| `DEBT-3` | The frozen synthetic `platform_boarding` design uses seven parallel boarding doors. | Extra service portals may compensate for an unmeasured boarding bottleneck and overstate the represented rolling stock's usable interface. | uncommitted design atop `0b938dcd`, Round 24 frozen into Round 25 | Seven doors produced real boarding progress, so Round 25 correctly froze it instead of retuning; however, no vehicle/line observation is linked to the count or spacing. | Link a line- and rolling-stock-specific observed door count/spacing dataset and validate the mapping, or explicitly reclassify the scene as synthetic and add a separate observation-matched design. | 27 |
| `DEBT-4` | The nominal exit-gate service envelope and observed completed throughput differ by about 19×. | Source-integrity success can be mistaken for evidence that the downstream gate/route service chain is physically calibrated. | `55543e2b` evidence baseline, re-registered Round 25 | Round-26 T2 reconciles residence exactly and shows exit delay is dominated by movement plus upstream waiting, but does not reproduce the historical 1400/74 ratio from one cohort. Closing on that explanation would relax T7. | Record per-lane open, service-ready, idle-underfed, blocked, opportunity, completion, and effective-window measures in one cohort and reconcile them with `3 × 55 persons/min`, or replace the nominal parameter with calibrated held-out evidence. | 27 |
| `DEBT-6` | Exit admission finiteness was accepted without a binding observation: capacity 73 equalled all 73 scheduled exit persons at the 240-step level and both flow exhaustion ratios were 0%. | A horizon-sized quota can be presented as a finite service resource even though it never constrains runtime flow, hiding a defective arrival envelope or residence-time sizing rule. | Round 25 T8 evidence, exposed by Round 26 finding A | Round-26 cap-40 produces a 35.90% exhaustion ratio, proving the mechanism binds, but only 50/73 exit demands spawn and 23 remain pending. The ten-minute sizing run then fails closed at finite entry decision holding. | Produce a pre-registered underconfigured counterexample with positive exhaustion and terminal source integrity, then recompute and validate entry/exit capacity on a formal-demand ladder without a horizon-sized quota. | 27 |

## Retired in Round 26

| id | retirement evidence | result |
|---|---|---|
| `DEBT-2` | `alignment/output/round26/T5_T6_service_chain_acceptance.json` | Across 240/480 × seeds 42/43/44, replans are 0/1/1 and 0/1/1 out of 156, all at or below 0.641%; source integrity passes and liveness is zero. The 600/900 seed-42/43 cross-checks also remain below 1%. |
| `DEBT-5` | `alignment/output/round26/T5_T6_service_chain_acceptance.json` | Placement retries are 0/156 in all six formal cohorts and all four long-window cross-checks; stable waiting-capacity and stalled-platform counters remain visible, with source integrity and liveness unchanged. |

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
