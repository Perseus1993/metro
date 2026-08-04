# Metro Station Sandbox Development Protocol

## Failure Audit Protocol

Movement degradation is not allowed. If JuPedSim is unavailable, a JuPedSim tick
fails, or a JuPedSim result is inconsistent with the requested agents, raise a
runtime error. Do not hide degraded behavior behind scattered `print()` calls or
broad exception suppression.

Rules:

1. Movement backend failures must raise instead of switching to a simpler
   movement model.
2. Startup diagnostics should print once per run, for example missing
   `station_design` or data profile quality degrading from normal workday to
   all-day mean.
3. High-frequency runtime diagnostics must be aggregated before printing.
4. Structural impossibilities should raise in development instead of silently
   degrading. Examples: no facilities for a declared stage, invalid route keys,
   or plan state conflicts.
5. Suppressed exceptions must be audited before suppression. If a suppression
   becomes frequent, it is a bug report, not normal operation.
6. Audit output must be generated through `audit.py`; do not introduce ad hoc
   `print()` statements in simulation logic.

Severity guide:

- `info`: expected diagnostic context that helps explain the run.
- `warning`: automatic degradation outside movement, such as data-source
  quality downgrades.
- `error`: an invariant was violated but the model can still preserve a
  diagnostic snapshot.

Recommended code shape:

```python
model.audit.record(
    "station_geometry_missing",
    source="layout_graph",
    severity="warning",
    step=model.step_index,
    count=1,
    context={"reason": "station_design_missing"},
)
```

The audit stream is a debugging surface and a design signal. If degraded
diagnostics show up repeatedly in normal runs, fix the model or make the
degradation an explicit scenario setting outside physical movement.

## Behavior Modeling Protocol

Passenger intent must stay region-to-region. Do not encode a new flow as a
hand-authored chain of decorative waypoints when it can be expressed as:

1. a source region,
2. a destination region,
3. a station graph route,
4. typed facility and queue actions.

Intermediate behavior should be explicit: Goal Runtime selects and commits a
facility, then commands walking, queue entry, waiting, use, release, and audited
replanning when progress stalls. `PassengerAgent` and `AgentPlan` must not make
those strategic decisions. The behavior contract lives in
`PASSENGER_BEHAVIOR_MODEL.md`.

Replanning is part of the model, not a hidden patch. A stalled passenger may
choose a second option only through an audited Goal Runtime decision, such as a
different gate lane, vertical transport, or boarding door that is still valid
for the same region goal.

Facility choices should use generalized cost rather than hard-coded "pick the
shortest queue" rules. When randomness is needed, use a logit-style selector:
rank by walking time, queue delay, preference penalties, and replan penalties,
then sample from that cost distribution. This preserves heterogeneity without
turning congestion into an invisible patch.

## Test Protocol

Before handing off simulation architecture changes, run:

```powershell
python -m unittest discover -s tests
```

Experiment and stress commands are release gates, not report-only tools:

- an experiment execution error or `trajectory_report.pass_fail == "fail"`
  must return a non-zero process exit code;
- use `--fail-on-warn` when warnings must also block a release candidate;
- stress runs only become acceptance runs when at least one explicit threshold
  such as `--min-completion-rate` or `--max-final-station-persons` is supplied;
- stress matrices checkpoint CSV, JSON, and Markdown outputs after every case,
  so a timeout still leaves completed cells and their final state diagnostics;
- production acceptance requires strict JuPedSim, a physical clock, active Goal
  Graph planning, an explicit station design, an independently validated
  calibration profile, and a non-zero clearance window.

When a change touches routing, design schema, facility choice, or movement
backends, tests should cover at least one of:

- template validation and graph compilation,
- a deliberately broken design that must fail validation,
- passenger intent completion for enter/exit/transfer,
- movement backend selection and JuPedSim error behavior,
- render payload shape for graph debugging.

## Micro-Scene Probe Protocol

When a facility behavior is unclear, isolate it before composing the full
station. The probe should expose a complete source/process/sink loop, keep the
movement and facility-service boundary explicit, and include both animation and
stress outputs.

The current references are the turnstile and vertical-flow probes:

```text
TURNSTILE_FLOW_PROBE.md
VERTICAL_FLOW_PROBE.md
```

Use that pattern for future small scenes such as platform boarding doors,
transfer bottlenecks, and facility-choice merge zones.

## Dynamic Disruption Protocol

Dynamic disruption tests must use step-boundary, serializable availability
events. A release result must retain the applied transition log and prove that no
facility service started during a disabled interval. Reopening must not
retroactively timestamp service inside the outage window. Queued passengers may
replan immediately; service that started before the closure is allowed to
finish.

Train-service disruption tests must distinguish an in-progress dwell from a
future scheduled arrival. Suspending service must not eject a train already at
the platform, and recovery must not synthesize an off-timetable arrival. Each
cancelled scheduled arrival and any arrival during suspension must remain in the
release evidence.

Passenger demand must remain conserved when a train is cancelled. Upstream
alighting demand may be deferred, but it must remain in the acceptance
denominator and satisfy `scheduled = spawned + still_deferred` at every final
result.

An active-service equipment fault must preserve passenger position and service
state while movement is unavailable. It must not start new service, teleport a
passenger to the release point, or retain the pre-fault predicted completion
time. Release acceptance must fail when a disabled facility still contains
passengers at the horizon.

Combined-emergency release evidence must contain both positive and negative
controls. A zero-person case must clear exactly, a nominal case must satisfy all
configured gates, a fully blocked egress case must retain every passenger and
fail explicitly, and an overload case must fail through completion, clearance,
remaining-population, or density limits without violating population
conservation.

## Statistical and Production Release Protocol

A release claim requires more than a small deterministic seed grid. Every
required population must have at least 30 independent seeds, zero execution and
acceptance failures, percentile summaries, and a deterministic bootstrap 95%
interval for the mean. A checkpoint may be resumed only when its configuration
fingerprint matches the requested experiment.

One-at-a-time sensitivity tests must perturb walking speed, gate service rate,
density slowdown, and disruption timing around a declared baseline. A parameter
with no measurable response in clearance time or peak local density is a model
influence failure and blocks release until the scenario exercises that behavior
or the parameter wiring is corrected.

Long-soak evidence must preserve active population through the complete time
horizon. Record expected and actual frame counts, population accounting, wall
time, real-time factor, and peak traced memory. Early termination after clearing
the station is not long-duration evidence. A timed-out 60-minute run remains a
blocker even if a shorter diagnostic run completes.

Calibration status and dataset identifiers are metadata contracts. Production
validation requires matched independent observations with per-case clearance
time and peak local density, plus reported MAE, RMSE, and MAPE against frozen
simulation outputs. Missing real observations must produce a blocked result;
simulation output must never be reused as its own validation data.

The aggregate release gate must retain all blockers rather than short-circuiting
at the first failure. Required components are emergency controls, per-population
reliability, sensitivity, long-soak performance, independent calibration, and
explicit operator/fire-authority approval of the density threshold. Production
ready is true only when every component passes.

JuPedSim parameters that appear in a release sweep must control live agent
state. Desired walking speed and density slowdown must be written to the
operational model before integration; computing a slowdown metric without
applying it is a release-blocking wiring defect. A sensitivity scenario must
show non-zero exposure to the target facility or parameter.

When no facility is eligible, the passenger must enter an explicit wait state.
Repeatedly sending a stationary passenger through physical integration is both
incorrect state semantics and a performance defect. Facility recovery must wake
the passenger and retry the same stage without losing Goal Graph commitment.

Numerical timestep changes require paired-seed validation against the reference
step. Compare completion, clearance, and peak density before considering any
speedup. A faster candidate that exceeds a predeclared error limit must be
rejected rather than accepted by relaxing the limit after results are known.

Evidence from parallel seed chunks may only be merged when the model evidence
version and configuration fingerprint are identical and run IDs are unique.
Any failed seed remains in the merged reliability denominator and blocks the
release even when percentile summaries otherwise look acceptable.
