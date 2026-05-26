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

Intermediate behavior should be explicit: choose facility, walk to queue tail,
join queue, wait, use facility, release to the next region, and replan if
progress stalls. The behavior contract lives in
`PASSENGER_BEHAVIOR_MODEL.md`.

Replanning is part of the model, not a hidden patch. A stalled passenger may
choose a second option only through an audited planner decision, such as a
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

When a change touches routing, design schema, facility choice, or movement
backends, tests should cover at least one of:

- template validation and graph compilation,
- a deliberately broken design that must fail validation,
- passenger intent completion for enter/exit/transfer,
- movement backend selection and JuPedSim error behavior,
- render payload shape for graph debugging.
