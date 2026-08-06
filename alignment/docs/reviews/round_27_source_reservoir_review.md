# Round 27 source-reservoir review

Date: 2026-08-06. Implementation freeze: `2bcd91fc`. Dynamic evidence revision: `afcb9036`.
480-step regression evidence revision: `aa9fa448`.

## Decision

The source-boundary implementation is complete, but the Round-27 release is blocked.

Entry demand now waits in an unbounded logical reservoir until it can be published into the
station. Train alighting uses a finite per-run manifest and cannot silently wait past departure:
each run either releases its manifest before departure or ends with the declared
`train_alighting_capacity_insufficient` outcome and records the remaining people as
`not_alighted`. Publication is a compensating transaction across the external reservoir, train
manifest, Alignment admission owner, Mesa agent, and JuPedSim body.

These changes make hidden loss structurally difficult and make the cap-40 counterexample valid.
They do not prove that the station provides stable useful service. Only two of five frozen dynamic
seeds pass. All three full-demand 480-step regression seeds violate the unchanged one-percent
stalled-region replan gate. A clearance horizon cannot yet be derived from a proven positive
minimum service rate and finite downstream tail. No trial-selected `clearance_tail = 900` is used.

## Acceptance matrix

| gate | result | evidence and interpretation |
|---|---|---|
| Source ownership and conservation | pass | Entry and alighting are reported separately as source-waiting, active, completed, not-alighted, and dropped partitions. No pooled source-wait headline is emitted. |
| Finite train departure semantics | pass | Normal runs release all alighting demand before departure; the under-capacity run fails with a structured policy outcome, records 85 not-alighted persons, and does not report a successful departure. |
| Dynamic non-vacuity, seeds 46–50 | **fail** | Frozen floors prevent a run from passing by leaving most people outside. Seeds 48/49 pass; 46/47/50 fail without changing the floors. |
| Round-26 service regression, 480-step seeds 42–44 | **fail** | Replan ratios are 4.782%, 1.646%, and 8.025%, all above 1%. Placement retries and liveness violations remain zero. |
| Cap-40 stress | pass | The run has 229 scheduled persons, 24 completions, 43 exhausted exit attempts out of 92, zero dropped persons, exact conservation, and the declared capacity-failure outcome. |
| Clearance prediction and run | **blocked** | No positive per-bottleneck minimum service rate plus finite downstream-tail proof is qualified, so no clearance duration or run is registered. |
| Round-27 release | **blocked** | Dynamic stability and clearance are both required; neither can be replaced by source conservation alone. |

## Dynamic evidence

The qualification cohort fixes the 240-step minimums before held-out evaluation: entry
scheduled/admitted/completed `167/107/18` and exit `134/134/35`. It also preserves the Round-26
limits of stalled-region replans at or below 1%, placement retries at or below 1%, and zero
liveness violations.

| seed | entry admitted / completed | exit admitted / completed | replan | placement | result |
|---:|---:|---:|---:|---:|---|
| 46 | 104 / 19 | 134 / 40 | 0.840% | 0% | fail: entry admission floor |
| 47 | 93 / 17 | 134 / 34 | 2.643% | 0% | fail: four checks |
| 48 | 108 / 20 | 134 / 37 | 0.413% | 0% | pass |
| 49 | 107 / 22 | 134 / 39 | 0.830% | 0% | pass |
| 50 | 104 / 17 | 134 / 38 | 1.681% | 0% | fail: three checks |

Every run has zero dropped persons, exact per-flow conservation, and zero liveness violations.
Those properties show that the source boundary works; the failed throughput and replan checks show
that useful service is not stable enough to release.

The independent 480-step probes use one clean revision and one runtime cohort. Seeds 42/43/44
complete 163/156/142 persons respectively, conserve all 601/601/600 due persons, and release both
train manifests before their departures. Their replan ratios nevertheless reach 4.782%, 1.646%,
and 8.025%. This reopens `DEBT-2`. All three placement ratios are zero, so `DEBT-5` remains retired.

## Stress and physical train policy

With exit admission capacity forced to 40, the mechanism is non-vacuous: 43 of 92 admission
attempts exhaust capacity. The run completes 24 people and conserves all 229 people across entry
source waiting, station-active, completed, and train-bound not-alighted states. The affected train
records 49 released and 85 not-alighted passengers, ends with
`train_alighting_capacity_insufficient`, and does not depart successfully.

This retires `DEBT-6` under the new explicit partition contract. It does not claim that carrying
passengers onward is desirable; it proves that the finite train has an explicit, auditable outcome
instead of an impossible infinite onboard waiting pool.

## Independent implementation audit

Eight P1 findings were corrected before review freeze:

| finding | disposition |
|---|---|
| Constructor failure could leave a ghost Mesa agent or admission owner. | Passenger publication now owns compensating rollback across agent, scheduler, JuPedSim, and admission state. |
| Alighting publication could commit one of three ledgers without the others. | Reservoir, manifest, and Alignment admission changes use preflight plus compensating rollback. |
| The manifest did not authorize live boarding capacity and over-capacity demand raised a naked value error. | Boarding reserve/commit/cancel use the manifest; insufficient capacity becomes a structured run outcome. |
| A missing or cancelled train could leave an unmatched manifest remainder. | Whole-manifest cancellation accounts for the remaining Alignment and reservoir demand. |
| Reservoir closure, right-censoring, and a writable pending scalar created competing truths. | Lifecycle closure is explicit; right-censored persons remain a subset of source waiting; pending alighting is a read-only reservoir view. |
| Gate evaluation accepted caller-synthesized evidence. | Gates recompute frozen evidence hashes, require exact revisions and evidence classes, and independently reconstruct conservation and liveness checks. |
| The qualification hash covered the runs but not the resulting frozen floors. | A second immutable hash now covers every floor field; the validator also requires the exact qualification revision and independently derives each minimum from the frozen runs. |
| Clearance could accept a zero-person manifest for nonzero scheduled alighting demand. | The gate now requires total planned and released manifest persons to equal scheduled alighting demand, in addition to the per-manifest departure checks. |

The final structured audit is recorded in `alignment/docs/agent_round27_final_audit.json`. Its
post-remediation falsification rerun reports no remaining P0 or P1 findings.

## Verification and evidence hygiene

- The current Round-27 reservoir, manifest, runtime, acceptance, and executor suite reports
  87 passed and 7 skipped. The post-extraction transaction and two P1 bypass regressions are
  included in that run.
- Ruff passes on the extracted publication transaction and its caller; the broader Round-27 Python
  change set passed before evidence generation.
- The source-size ratchet still has one known baseline failure:
  `facilities/runtime_base.py` is 981 lines against a 970-line limit. The new
  `passenger_demand.py` change is 720 lines against its 765-line ratchet.
- The five dynamic artifacts use the exact frozen qualification hash
  `a8cc900e3e2b09950005a7e8ed702988b37c137438779505a885886640da6ca7` and floor hash
  `9d729f45cda6bec4db0888363a25b0f0f3d9cc31727feb15aba21ac849150edc`.
- Re-evaluating the five stored flow snapshots through the remediated validator reproduces the
  same seed statuses and failed-check sets: fail/fail/pass/pass/fail for seeds 46–50.
- The three 480-step probes share revision `aa9fa448`, Metro source fingerprint
  `81e4caf159ffd31565298f1c8c064c0ab2158b925e5c3ba23aa4a2bd30854980`, and Alignment analysis
  fingerprint `fae0b4082696ba4e21ea419f517bf9c84c9085e255b8b3dd3d275837f2a70f35`.
- Clearance remains `prediction_unavailable`; no observed completion time is relabeled as a
  preregistered prediction.

## Debt and next work

Round 27 retires `DEBT-6`, reopens `DEBT-2`, and keeps `DEBT-5` retired. `DEBT-1`, `DEBT-3`, and
`DEBT-4` move explicitly to Round 28 because their observation or service-reconciliation evidence
was not produced. Four debts remain against the five-entry Round-25 baseline, so
`registered_debt_delta = 4 - 5 = -1`.

The next implementation should diagnose the shared stalled-region contexts in seeds 47/50 and
480-step seeds 42–44 without changing the floors or denominator. Clearance work should begin only
after a positive lower service rate and finite downstream tail are derived for every bottleneck.
Until both conditions hold, the correct result is a conserved but release-blocked station model.
