# Round 26 downstream service-chain review

Date: 2026-08-06. Code freeze: `01f64607`. Evidence freeze: `e41bf08d`.

## Decision

Round 26 closes on the plan's explicit fallback, not on its full completion definition.

The platform-to-exit service-chain repair is real: `DEBT-2` and `DEBT-5` retire, all six formal
240/480 × seed 42/43/44 cohorts pass their unchanged one-percent gates, and exit residence becomes
fully observable by 480 steps. The same evidence does **not** explain the historical 18.9× nominal
service gap, validate a binding exit-admission capacity with terminal source integrity, or produce
the formal high-demand ladder. T7 is deferred and T8–T10 stop at a finite entry decision-holding
capacity error. No criterion was widened to manufacture a complete ladder.

This is therefore a **partial, fail-closed Round-26 result**. The service-chain fixes are accepted;
the sizing/ladder release claim remains on hold.

## Blockers B0–B2

| item | result | evidence |
|---|---|---|
| B0 same-tick provenance | pass | The same-tick gate, JuPedSim recovery, and `runtime_base.py` size failure all reproduce at `55543e2b`; none was introduced by PR-2. Prompt J also found two post-baseline size regressions. `026f9588` removed both; the current size gate reports only the unchanged `runtime_base.py` 981 > 970 offender. |
| B1 register `DEBT-6` | pass | Exit capacity 73 equalled all 73 short-probe exit demands, so the zero-exhaustion result was recorded as vacuous rather than accepted. |
| B2 expiry renegotiation | pass, explicitly widened | `DEBT-1` moved to 27 because its passenger-emergence observation is data-blocked. At closure, `DEBT-4` and `DEBT-6` also move to 27 for the concrete failed criteria below. The register records the reasons and net delta; no expiry changed silently. |

The B0 distinction matters: “PR-1 did not touch the file” does not imply “PR-2 did not introduce
the failure.” Only the detached `55543e2b` execution establishes provenance. Conversely, one
unchanged offender does not excuse additional offenders in a multi-file ratchet test.

## Task result matrix

| task | result | review conclusion |
|---|---|---|
| T1 mechanism counters | pass | Placement retry, waiting-capacity retry, and stalled-platform parking expose stable numerator, denominator, and ratio fields. |
| T2 time attribution | pass | Both flows use the same five phases. Independent owner-level recomputation over the current aliases gives maximum residual 0 and zero unclassified steps. |
| T3 cap-40 falsification | **fail** | The exit mechanism binds, but source integrity does not survive: 50/73 spawned, 23 pending. |
| T4 censoring sensitivity | pass for residence W only | At two-minute demand, p99 is fully observed by 480 and stable through 900. This does not create a validated formal-demand capacity. |
| T5 stalled replan | pass | Six formal ratios are 0%, 0.641%, 0.641% at both 240 and 480; all are ≤1%. |
| T6 placement retry | pass | All six formal cohorts record 0/156 placement retries; source integrity passes and liveness is zero. |
| T7 nominal service gap | **deferred to Round 27** | T2 explains residence but cannot reconstruct 1400/74 from one cohort. The criterion is unchanged. |
| T8 resizing | **blocked** | The ten-minute, 1200-step seed-42 measurement stops at step 192 with finite entry decision-holding capacity exhausted. No capacity is registered. |
| T9 ladder | not run | Stopped after T8; no 240→480→600→900 formal ladder is claimed. |
| T10 multi-seed ladder | not run | Short-demand T5/T6 multi-seed evidence is not relabeled as a formal finite-capacity ladder. |
| T11 debt register | pass | Four debts remain open against the five-entry Round-25 baseline: `registered_debt_delta = -1`. |
| T12 review | pass | This document is committed separately from the evidence/debt freeze. |

## Unified service-chain diagnosis and repair

The Round-25 symptoms were coupled. Reservation order was being treated as physical queue order,
multiple exit lanes converged through shared outer geometry, valid holding cells could still have
body-blocked paths, and release-apron capacity counted raw lattice rows rather than usable
body-clear rows. Under load, early reserved owners could be stranded behind later bodies while the
gate FIFO remained empty; replanning and placement retry then hid the physical deadlock.

Round 26 changed the chain in five related places:

1. Release capacity and holding exclusion now share the same body-clear geometry and bounded
   alternates.
2. Entry and exit holding rank unchanged finite cells by live-body path clearance.
3. Exit lanes fan out before their final lane ingress instead of sharing one exact waypoint.
4. Admission reservations remain finite, but gate FIFO order starts at physical lane-mouth capture;
   approach-claim compaction no longer retargets a body away from the lane tail.
5. A genuinely stalled, committed owner adjacent to its compiled gate bank may finish the tail
   turn toward its reserved inner slot under a bounded geometric proof.

These are geometry and lifecycle rules, not seed-specific coordinates or threshold suppression.
The per-commit physical/general/anti-patch answers are frozen in
`alignment/docs/round26_fix_contracts.md`. Replan event names, denominators, the one-percent gates,
and the T7/T9 criteria were not weakened.

## Quantitative evidence

### T5/T6 formal acceptance

| horizon | seed | spawned | replan | replan ratio | placement retry | source | liveness |
|---:|---:|---:|---:|---:|---:|---|---:|
| 240 | 42 | 156 | 0 | 0% | 0 | pass | 0 |
| 240 | 43 | 156 | 1 | 0.641% | 0 | pass | 0 |
| 240 | 44 | 156 | 1 | 0.641% | 0 | pass | 0 |
| 480 | 42 | 156 | 0 | 0% | 0 | pass | 0 |
| 480 | 43 | 156 | 1 | 0.641% | 0 | pass | 0 |
| 480 | 44 | 156 | 1 | 0.641% | 0 | pass | 0 |

Seeds 42/43 at 600 and 900 retain the same 0-or-1 replan result, zero placement retries, source
pass, and zero liveness violations. This retires `DEBT-2` and `DEBT-5` without relying on the failed
formal sizing ladder.

### T2/T4 residence and censoring

| seed | exit p50 | exit p90 | exit p99 | complete/censored | horizons with same full result |
|---:|---:|---:|---:|---:|---|
| 42 | 124 | 220 | 294 | 73/0 | 480, 600, 900 |
| 43 | 133 | 210 | 303 | 73/0 | 480, 600, 900 |
| 44 | 126 | 212 | 278 | 73/0 | 480 |

The conservative short-demand exit W is 303 steps. For seed 42 at 900 steps, the exit phase
medians are travel 105, queue 6, service-ready wait 1, release-blocked 2, and completion 3. Travel
itself has median moving 56 and upstream wait 51. Phase totals exactly equal measured residence:
exit 9712/9712 and entry 3438/3438.

This replaces the original exit p50 219 with 124–133 in the repaired cohort and identifies the
remaining time as pre-gate movement/upstream waiting. It does not solve T7: the current evidence
does not record lane open, idle-underfed, blocked, service-opportunity, completion, and effective
window measures needed to reconstruct historical `1400 / 74 = 18.9189` in one cohort.

### T3 finite-resource counterexample

With exit capacity forced to 40 at 240 steps, exit admission records 78 attempts and 28 exhausted
attempts, a 35.897% ratio. The acquire/exhaust path is therefore non-vacuous. The same run has only
50 of 73 exit demands spawned, 23 pending, maximum pending residence 124, and a failed source gate.
`dropped=0`, conservation true, and liveness zero do not substitute for terminal clearance.
Consequently T3 fails and `DEBT-6` remains open.

Independent Prompt I also recomputed the fixed-window algorithm. Under full-horizon demand, exit
envelopes at 480/600/900 are 293/267/275, while scheduled totals are 293/367/550. The envelope is
not a monotonically growing horizon quota. However, current registered residence evidence does not
match the frozen source/analysis/formal-demand scope, so validated `required_capacity` remains null.
Raw envelope diagnostics are not registered as production capacities.

### T8 fail-closed blocker

The first formal-demand measurement used 1200 steps, seed 42, ten minutes of demand, and the control
arm. At step 192, passenger 272 exhausted the body-clear slots in `entry_gate_decision` and raised
`DecisionHoldingCapacityError`. This is a real finite service-layer boundary. Round 26 does not
enlarge the holding region, turn the exception into a warning, or lower the ladder criteria. T8,
T9, and T10 remain incomplete.

## Independent audit disposition

| prompt | status | disposition |
|---|---|---|
| J baseline provenance | found a P1, then remediated | All named failures pre-exist PR-2. The two newly detected source-size offenders were removed in `026f9588`; current rerun leaves only historical `runtime_base.py`. |
| H time attribution | overall fail; T2 pass / T7 fail | Zero-residual attribution is accepted. The missing one-cohort 18.9× reconstruction blocks T7 and `DEBT-4` retirement. |
| I finiteness | fail | T3 binds but fails source integrity; preflight capacity is unvalidated; T8 stops at step 192. `DEBT-6` remains open. |

Two P2 evidence-hygiene limits remain explicit. The generated artifacts record pandas 3.0.3 while
`alignment/uv.lock` currently resolves 3.0.5, so any future release-grade capacity evidence must be
rerun in a unified frozen environment. Also, ignored diagnostic `T5_T6_final_v2_*` files share a
name glob with current aliases; this review and the Git evidence freeze enumerate exact canonical
paths and do not include those superseded files.

## Verification

- Ruff over all Python changes from `7b31c58b..01f64607`: pass.
- Attribution, service-counter, and spatial-capacity subset: 25 passed.
- Gate-focused, bidirectional, probe, and stalled-ingress directed groups were green at the code
  freeze; the two larger combined invocations exceeded the 60-second command harness and are not
  counted as additional results.
- Source-size gate: one failure, exactly the unchanged baseline offender
  `facilities/runtime_base.py` at 981 > 970. No Round-26 source exceeds its ratchet.
- All ten canonical T4/T5/T6 evidence artifacts pass independent canonical self-hash checks and
  share Metro source tree `62f81265...`, analysis content `0a01992b...`, and runtime cohort
  `35d5481e...`.
- Raw canonical evidence and summaries are Git-frozen at `e41bf08d`.

## Debt accounting and scope boundary

Round 25 established five debts. Round 26 adds `DEBT-6`, retires `DEBT-2` and `DEBT-5`, and leaves
`DEBT-1`, `DEBT-3`, `DEBT-4`, and `DEBT-6` open. Therefore:

`registered_debt_delta = 4 current - 5 baseline = -1`.

The net decrease satisfies the register rule, while the individual expiry widenings remain
explicit. This round contains **no Step 6 conclusion** and claims **no retirement of DEBT-1 or
DEBT-3**. Proxy geometry, real passenger-emergence observations, the seven-door synthetic design,
cloud publication, and student release remain outside this review.

## Round 27 handoff

Round 27 should keep the existing criteria and proceed in causal order:

1. Make exhaustion of `entry_gate_decision` a conserved, waitable finite-capacity state under the
   identical ten-minute demand contract.
2. Regenerate residence evidence under one frozen lock/source/analysis/formal-demand scope so
   preflight produces validated capacities.
3. Re-run cap 40 without changing the capacity, horizon, seed, or source-integrity criteria; require
   both positive exhaustion and terminal clearance.
4. Instrument one-cohort lane opportunity accounting and either reconcile `3 × 55 persons/min`
   with completions or replace 55 with held-out calibration evidence.
5. Only then run the unchanged 240→480→600→900 ladder and multi-seed gates.

The important carry-over is not “finish the missing steps.” It is the discovered service contract:
finite waiting must express backpressure as ownership plus retry, not as a hard exception, and
finite admission must be observed binding without sacrificing terminal source integrity.
