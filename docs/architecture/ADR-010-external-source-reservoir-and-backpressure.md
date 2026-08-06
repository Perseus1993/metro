# ADR-010: Separate External Demand Reservoirs from Finite Station Storage

- Status: Accepted
- Date: 2026-08-06
- Scope: Metro demand publication, alighting release, Alignment dynamic/clearance evidence

## Context

The runtime already defers demand when source placement or downstream ownership is unavailable,
and Alignment preserves scheduled entry demand in a FIFO until publication succeeds. Round 26
showed that the remaining high-demand failure is not lost demand: a published body can reach
`entry_gate_decision` without a body-clear holding slot and terminate the run. The old acceptance
contract also requires every scheduled body to be published by a fixed horizon, conflating an open
demand boundary with finite station storage.

Two physical boundaries must not be conflated:

- Entry demand can wait outside the represented station in an unbounded logical reservoir.
- Alighting demand belongs to a finite train manifest and may wait only until the train's declared
  departure deadline. It cannot remain attached to a departed train.

An unbounded source also creates a new falsification risk: a run can conserve every person while
serving almost nobody. Dynamic throughput and clearance therefore need preregistered quantitative
floors rather than report-only queue metrics or a trial-selected clearance horizon.

## Decision

### External entry reservoir

Represent not-yet-published entry demand as ordered source records outside physical station
occupancy. A record remains owned by the reservoir until admission credit, a certified source
position, and the first safe downstream ownership are all available. Passenger construction and
native placement remain transactional; a failed attempt publishes no Mesa/JuPedSim body and leaks
no token.

### Finite train alighting manifest

Bind alighting records to one immutable train run id `(platform_id, arrival_sequence)`. Each arrival
owns a finite `TrainExchangeManifest` containing inbound load, planned alight, through load,
released alight, boarded load, close step, and departure result. The manifest must prove
`planned_alight <= inbound_load <= capacity` and `through_load = inbound_load - planned_alight`.

The initial Round-27 policy is `FAIL_CAPACITY`: if records remain when that train reaches its
departure deadline, stop normal execution with structured status
`train_alighting_capacity_insufficient`, close the manifest with `not_alighted`, and do not record a
successful departure. This is an expected model outcome, not an unhandled exception. Do not move
those records to a later train, extend dwell, or leave them attached to a departed train. Bounded
dwell extension and carry-forward are separate future policies.

A successful departure must prove both:

```text
planned_alight = released_alight
alighting_release_complete_step <= actual_departure_step
departure_load = through_load + boarded <= capacity
```

### Expected backpressure versus invalid configuration

Temporary lack of body-clear storage is a typed wait result. Zero certified capacity, missing
topology, impossible group size, or an invalid source-to-first-owner contract remains a fail-fast
configuration error. An already published passenger never returns to a source reservoir; it keeps
its current upstream physical ownership while waiting for downstream capacity.

### Evidence contract

Dynamic, clearance, and stress runs are distinct:

- Dynamic: source pending is allowed, but admitted and completed persons per flow must meet
  preregistered floors derived before execution.
- Clearance: no arbitrary tail is selected. At demand cutoff, predict an upper bound from the
  remaining population upstream of each bottleneck, a proved minimum service rate, and the
  downstream completion tail. The prediction and inputs are frozen before the clearance segment.
- Stress: underconfiguration must produce a positive exhaustion numerator while preserving
  conservation and typed waiting; terminal clearance is evaluated only in the clearance segment.

For bottleneck `b`:

```text
T_b = ceil(N_b(cutoff) / mu_b_min) + L_b_downstream
T_clearance_upper = max_b(T_b)
```

If the implementation proves that bottlenecks cannot pipeline, the preregistration must use the
more conservative serial sum. An uncalibrated nominal rate is diagnostic only and cannot supply
`mu_b_min`. If no lower bound is proved, clearance status is `prediction_unavailable`, not pass.

Source wait duration is never pooled across semantic boundaries. Entry outside-station wait and
on-train alighting delay are reported separately per entrance or train arrival. Only conservation
counts may be aggregated.

## Invariants

At every step, per semantic boundary:

```text
scheduled = source_waiting + active_inside + completed + not_alighted + dropped
dropped = 0
```

`not_alighted` is legal only in a closed failed train manifest. It is never legal for an entry
boundary and never counts as successful station service.

Additional contracts:

1. Each demand record has exactly one owner and one stable sequence id.
2. Publication occurs at most once and only after physical placement succeeds.
3. FIFO and declared group atomicity hold within each source boundary.
4. A train has no alighting record after its actual departure, and a failed manifest has no
   successful departure event.
5. Expected capacity saturation does not throw an unhandled exception.
6. Invalid geometry does not become an infinite retry.
7. Dynamic admission and completion floors prevent a zero-service pass.
8. Round-26 replan and placement-retry retirement evidence remains a regression gate.

## Consequences

- Station occupancy and movement can be studied without pretending that the model includes an
  unlimited physical forecourt.
- External queues may grow under overload, but their size and wait are visible and cannot replace
  minimum station throughput.
- Alighting infeasibility becomes a physically meaningful run result instead of silent retention.
- Existing Round-25 source-integrity checks must split into dynamic conservation and clearance
  completion contracts; fixed-horizon `spawned == scheduled` is no longer universal.
- A stale token-residence artifact no longer blocks runtime startup. Its last deterministic envelope
  may remain as a finite diagnostic credit, explicitly marked `stale_or_unavailable`; it is neither
  a physical-storage proof nor eligible for a dynamic floor or clearance prediction.
- Historical 18.9x nominal exit-service calibration, real entrance geometry, and Step 6 remain
  separate credibility work rather than hidden release gates for this runtime contract.

## Acceptance prerequisites

Before implementation evidence is accepted:

1. Verify Round-27 ancestry contains the Round-26 code freeze `01f64607` and preserve the exact
   DEBT-2/DEBT-5 retirement gates.
2. Verify the same-tick gate failure provenance against the existing detached `55543e2b` evidence
   before modifying admission/gate paths, then record the current-head value.
3. Freeze the source record schema, temporary-wait result, invalid-configuration result, and train
   departure policy before the admission integration commit.
4. Freeze every throughput-floor and clearance-prediction input before its measured run.

## Baseline decision

The Round-27 implementation base contains the Round-26 code freeze `01f64607`. The same-tick gate
test reproduces the identical `expected active_passes=4, actual=1` mismatch at both detached
baseline `55543e2b` and Round-27 parent `27e57b4c`; it is classified as pre-existing and is not a
source-capacity tuning target. Round-26 DEBT-2 and DEBT-5 retirement gates remain unchanged.
