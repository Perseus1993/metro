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

Round 27 replaces the terminal `spawned == scheduled` source contract with explicit external
entry waiting and finite, train-bound alighting manifests. This retires `DEBT-6`: the frozen
cap-40 stress run records 43 exhausted attempts out of 92 exit admissions, completes 24 persons,
drops nobody, conserves every person across source/active/completed/not-alighted partitions, and
ends with the declared `train_alighting_capacity_insufficient` policy rather than an exception.
The earlier 480/600/900 envelope falsification also remains non-monotone, so the mechanism is not
accepted merely because it equals one horizon's demand total.

Round 27 simultaneously reopens `DEBT-2`. Its Round-26 retirement evidence used the shorter
service-chain cohort; on the frozen full-demand held-out contract, seeds 47 and 50 record stalled
replan ratios 2.643% and 1.681%, above the unchanged one-percent criterion. `DEBT-5` stays retired:
all five held-out seeds have zero placement retries. `DEBT-1`, `DEBT-3`, and `DEBT-4` move to Round
28 with explicit reasons below. Four entries therefore remain open and
`registered_debt_delta = 4 - 5 = -1`; the round neither hides the reopened service instability nor
adds a net debt without retiring another.

## Open debt

| id | what | masks | introduced | justification | retire_evidence | expiry_round |
|---|---|---|---|---|---|---|
| `DEBT-2` | Full-demand held-out seeds still depend on repeated stalled-region replanning above the one-percent recovery budget. | A nominally working service chain may rely on recovery reroutes instead of stable physical progression. | Round 25, retired on the shorter Round-26 cohort, reopened by Round-27 held-out seeds 47/50 | The source/backpressure redesign is conserved and placement-stable, but held-out replan ratios 2.643% and 1.681% violate the unchanged gate. Lowering the floor or denominator would hide the instability. | Diagnose the seed-47/50 stalled-region event contexts, remove the shared physical cause, then pass the same frozen 240-step floors and replan threshold on seeds 46–50 plus 480-step seeds 42–44. | 28 |
| `DEBT-3` | The frozen synthetic `platform_boarding` design uses seven parallel boarding doors. | Extra service portals may compensate for an unmeasured boarding bottleneck and overstate the represented rolling stock's usable interface. | uncommitted design atop `0b938dcd`, Round 24 frozen into Round 25 | No line/vehicle door observation was added in Round 27; source-boundary engineering cannot manufacture that evidence. The expiry is explicitly moved one round. | Link a line- and rolling-stock-specific observed door count/spacing dataset and validate the mapping, or explicitly reclassify the scene as synthetic and add a separate observation-matched design. | 28 |
| `DEBT-4` | The nominal exit-gate service envelope and observed completed throughput differ by about 19×. | Source-integrity success can be mistaken for evidence that the downstream gate/route service chain is physically calibrated. | `55543e2b` evidence baseline, re-registered Round 25 | Round-27 source accounting prevents hidden loss, but dynamic held-out service still fails and no one-cohort lane opportunity reconciliation was produced. The criterion is not relaxed; expiry moves explicitly. | Record per-lane open, service-ready, idle-underfed, blocked, opportunity, completion, and effective-window measures in one cohort and reconcile them with `3 × 55 persons/min`, or replace the nominal parameter with calibrated held-out evidence. | 28 |
| `DEBT-1` | `platform_boarding` shifts the alighting-source lattice laterally by 10 m. | A source/boarding geometry that may overlap or be infeasible when based on the unshifted train-door geometry. | `8d31e11f`, Round 23 carry-over | No observed emergence-position data was added in Round 27; the new manifest fixes ownership, not geometry calibration. This data-blocked expiry moves explicitly. | Replace the constant with line/vehicle observation data (including uncertainty), then pass source preflight and a held-out multi-seed trajectory comparison without an arbitrary translation. | 28 |

## Retired in Round 27

| id | retirement evidence | result |
|---|---|---|
| `DEBT-6` | `alignment/output/round27/T9_exit_capacity_40_seed42_final.json` and `alignment/output/round27/T7_T9_held_out_summary.json` | Exit capacity 40 binds with 43/92 exhausted attempts (46.739%), while demand remains non-vacuous, 24 persons complete, dropped stays zero, all 229 due persons partition exactly, and 85 passengers still aboard are recorded as `not_alighted` under the declared failure policy. This tests a finite mechanism without treating external waiting as loss or requiring an impossible silent train reservoir. |

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
