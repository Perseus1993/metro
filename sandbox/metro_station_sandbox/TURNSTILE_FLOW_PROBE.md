# Turnstile Flow Probe Protocol

This document records the small-scene protocol for validating turnstile behavior
before composing a full station. The goal is to make the gate logic inspectable:
source demand, pedestrian approach, queue capture, gate service, and sink must be
debuggable as one isolated process.

## Purpose

Do not debug the whole station first when a facility behavior is still unclear.
For turnstiles, start with this micro-scene:

```text
source -> JuPedSim pre-gate approach -> ordered gate queue -> gate service -> sink
```

The probe is intentionally smaller than a station. It excludes vertical
transfer, platforms, train dwell, station-wide routing, and the full renderer.

## Behavior Contract

The turnstile scene is split into explicit phases:

1. `source`: passengers are spawned according to a demand profile.
2. `pre_gate_approach`: active walking agents move toward a small fan of
   pre-gate merge targets. JuPedSim owns collision and local avoidance here.
3. `queue_capture`: once the approach target is reached, the passenger joins the
   facility queue. This is the boundary between pedestrian motion and facility
   service.
4. `queue_layout`: the queue is an ordered service structure, not a free-walking
   crowd. It uses a single head slot followed by staggered two-column slots.
5. `gate_service`: the stochastic gate is a single server. The head passenger
   occupies the gate for a sampled tap duration, with optional retry delay.
6. `sink`: a passenger is counted as departed only after service completes.

Important invariant: a passenger must not appear in `sink` unless a gate service
event has completed.

## Modeling Rationale

This probe deliberately combines three model layers:

- Pedestrian dynamics: JuPedSim handles the walking and collision behavior while
  passengers approach the pre-gate merge zone.
- Bottleneck behavior: the fan-shaped approach compresses flow before the gate
  instead of making every passenger target one exact point.
- Queueing/service system: the gate is treated as a single-server queue with
  stochastic service time, retry probability, and FIFO release.

This avoids a common bad simplification: driving all passengers to one queue
anchor and instantly teleporting them through the gate.

## Code Ownership

Main probe:

```text
scripts/run_turnstile_flow_probe.py
```

Key pieces:

- `TurnstileProbeModel`: source, sink, JuPedSim adapter, and frame snapshots.
- `turnstile_pre_gate_targets()`: fan targets before the queue capture boundary.
- `turnstile_queue_slots()`: single head slot plus staggered two-column queue.
- `StochasticGateProcessAgent`: explicit tap duration, tap failures, and retry
  delay for isolated turnstile testing.
- `animation_html_document()`: lightweight debug renderer for the probe.

Shared facility behavior touched by this work:

- `facilities/runtime_base.py`: empty queues must not accumulate service credit.
- `facilities/facility_queue.py`: queue layout can spread passengers into
  ordered slots instead of leaving shared-anchor arrivals stacked together.

Regression tests:

```text
tests/test_turnstile_flow_probe.py
```

## Demo Command

Use this to generate the currently useful visual probe:

```powershell
python scripts\run_turnstile_flow_probe.py `
  --demands 1800 `
  --gate-services 12 `
  --minutes 1 `
  --tick-seconds 1 `
  --drain-seconds 420 `
  --walk-units-per-tick 0.7 `
  --movement-backend jupedsim `
  --jupedsim-iterations-per-tick 20 `
  --gate-service-mode stochastic `
  --tap-jitter-seconds 0.5 `
  --tap-failure-probability 0.08 `
  --tap-retry-seconds 1.4 `
  --quiet
```

Serve the generated animation if no server is already running:

```powershell
python -m http.server 8787 --bind 127.0.0.1 -d output\turnstile_flow_probe
```

Open:

```text
http://127.0.0.1:8787/turnstile_flow_probe_animation.html
```

Expected visual checks:

- Blue walking passengers fan into the pre-gate merge zone.
- Yellow queue passengers form staggered slots before the gate.
- Purple passing passenger can be observed occupying the gate.
- The side panel shows `service=1` during active service.
- `tap failures` is nonzero when failure probability is enabled.
- `sink` increases only after service completion.

## Stress Command

Use this matrix before relying on the turnstile behavior in a larger station:

```powershell
python scripts\run_turnstile_flow_probe.py `
  --demands 1200,1800,2400 `
  --gate-services 10,12,18 `
  --seeds 1,2,3 `
  --minutes 1 `
  --tick-seconds 1 `
  --drain-seconds 480 `
  --walk-units-per-tick 0.7 `
  --movement-backend jupedsim `
  --jupedsim-iterations-per-tick 20 `
  --gate-service-mode stochastic `
  --tap-jitter-seconds 0.5 `
  --tap-failure-probability 0.08 `
  --tap-retry-seconds 1.4 `
  --output-stem turnstile_flow_probe_stress `
  --quiet
```

Generated stress outputs:

```text
output/turnstile_flow_probe/turnstile_flow_probe_stress.csv
output/turnstile_flow_probe/turnstile_flow_probe_stress.json
output/turnstile_flow_probe/turnstile_flow_probe_stress.md
```

The stress run should report:

- `errors = 0`
- `jupedsim_steps > 0` for JuPedSim runs
- `service_persons_max = 1` for one gate lane
- `source_persons = sink_persons + unserved_persons`
- `backlog = 0` only when the configured drain window is intentionally enough
- increasing demand or lower service should increase queue/wait metrics

## Acceptance Criteria

Before using this behavior as a building block in the full station:

1. Run the focused tests:

   ```powershell
   python -m unittest tests.test_turnstile_flow_probe
   ```

2. Run the full test suite after shared facility changes:

   ```powershell
   python -m unittest discover -s tests
   ```

3. Regenerate the demo animation and inspect the visual behavior.

4. Run the stress matrix and inspect worst cases:

   - `worst_queue_persons_max`
   - `p95_queue_wait_seconds`
   - `p95_system_seconds`
   - `tap_failures`
   - `worst_unserved_persons`

## Current Baseline

For the demo command above, the last known baseline was:

```text
source_persons = 30
sink_persons = 30
unserved_persons = 0
queue_persons_max = 22
service_persons_max = 1
tap_failures = 4
jupedsim_steps = 3356
p95_system_seconds = 253
```

For the 27-case stress command above, the last known baseline was:

```text
runs = 27
ok = 27
errors = 0
backlog = 0
worst_unserved_persons = 0
worst_queue_persons_max = 32
worst_service_persons_max = 1
tap_failures = 93
```

## How To Extend

When adding the next small scene, follow the same pattern:

1. Define the smallest source/process/sink loop.
2. Keep the movement backend and facility service boundary explicit.
3. Add animation fields that expose the internal state being validated.
4. Add focused tests for the discovered bug or invariant.
5. Add a stress command with enough seeds to catch stochastic regressions.

Do not start from full-station composition when the facility behavior itself is
still under inspection.
