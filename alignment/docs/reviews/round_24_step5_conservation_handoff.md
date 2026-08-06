# Round 24: Step 5 conservation handoff

Date: 2026-08-05 CST. Decision: **implementation still in review / release hold**.

## Tonight's boundary

The only success target is Step 5 source integrity: no lost entry demand, explicit
pending ownership, and conservation. Step 6 is deliberately out of scope. Its
`geometry_evidence_status=proxy` and low-density desired-speed proxy are data blockers;
runtime changes cannot make them observed-matched.

## Durable progress

- `d8b3bbc0` added the formal ladder/profile, preregistered saturated-flow artifact,
  bilateral 1.2--1.5 counterexamples, atomic publication coverage, and nightly seeds.
- `ba71c663` hardened shared-lane handoffs. The current uncommitted design replaces the
  formal shared bank with three fixed entry lanes and three fixed exit lanes.
- The boarding proxy now exposes seven independently queued train doors. The earlier
  six-door diagnostic improved boarding from zero to 31 and produced a 23-person train
  departure; this is progress evidence, not an acceptance result.
- A formal 900-step mixed run reached step 900 without a liveness violation. It failed
  closed at source acceptance: scheduled entry 417, spawned 373, pending 44, dropped 0,
  conservation true. No formal manifest was published.
- Atomic publication then exposed a Windows path-length defect at 261 characters in a
  nested ladder control. Transaction filenames are now short and the nested publication
  regression passes with the existing rollback tests.

## Single-variable 120-step falsification

Frozen inputs for both probes: current fixed-direction design, seven doors, seed 42,
2500/2200 persons/hour, 120 demand steps and 120 horizon steps. The second probe changed
only downstream finite-admission evidence to report effectively unbounded capacity; it
did not change the design, demand, gate service, movement model, or seed.

| Metric | Current finite admission | Unbounded admission probe |
|---|---:|---:|
| scheduled / spawned / pending entry | 83 / 75 / 8 | 83 / 83 / 0 |
| entry dropped / conserved | 0 / true | 0 / true |
| `capacity.admission_exhausted` | 90 | 0 |
| `passenger_demand_deferred_without_downstream_admission` | 89 | 0 |
| `placement.dynamic_blocked` | 12 | 16 |
| `passenger_liveness_violation` | 0 | 0 |

Interpretation: finite downstream ownership is the direct cause of entry source deferral.
Removing that gate admits all scheduled entry demand in the short probe. It does not fix
physical placement contention (`dynamic_blocked` rose slightly), so it is not sufficient
evidence that the same change repairs boarding or exit throughput. Do not turn the probe
into production behavior without a finite, physically owned upstream queue contract.

## P0 invariant

Alignment source backpressure now retains every due group as either admitted or pending.
`_require_alignment_source_conservation()` runs on every spawn phase and raises on the
first unowned group; Round 24 adds a direct regression for `requested=1, admitted=0,
pending=0`. Final publication additionally requires dropped persons zero.

## Next review unit

1. Keep the current design frozen and make one production change only: replace the
   approach-slot-only entry publication licence with a finite upstream admission resource
   that cannot form a body wall and cannot lose demand.
2. Run the 120-step tripwire first. Required: entry dropped 0, source conservation true,
   liveness violations 0; compare admission exhaustion rather than hiding it.
3. Only after that passes, compare the previous design with the same runtime code to
   separate door-count effects from runtime ownership effects.
4. Do not resume 600/900-step ladder runs until the short probe has a defensible finite
   ownership result. Do not work on Step 6 in this review unit.

Branch size at handoff: the two committed review units differ from `55543e2b` by 2,416
insertions/deletions across 30 files; the current worktree adds 545 insertions/deletions
across 17 files. These changes require splitting before merge.
