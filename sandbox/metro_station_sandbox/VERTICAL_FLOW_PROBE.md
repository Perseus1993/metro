# Vertical Flow Probe Protocol

This document records the small-scene protocol for validating escalator,
elevator, and stair behavior before composing a full station. The goal is to
make vertical transfer inspectable as an isolated source/process/sink loop.

## Purpose

Do not debug the whole station first when vertical-transfer behavior is still
unclear. Start with this micro-scene:

```text
source -> JuPedSim vertical approach -> ordered facility queue -> vertical service -> sink
```

The probe is intentionally smaller than a station. It excludes gates, platforms,
train dwell, full-station routing, and the production renderer.

## Behavior Contract

The vertical scene is split into explicit phases:

1. `source`: passengers are spawned according to a demand profile.
2. `vertical_approach`: active walking agents move toward a fan of pre-capture
   targets. JuPedSim owns collision and local avoidance here.
3. `queue_capture`: once an approach target is reached, the passenger joins the
   selected vertical facility queue.
4. `queue_layout`: the queue is an ordered service structure with a single head
   slot and staggered two-column slots.
5. `vertical_service`: the shared runtime handles facility-specific service:
   escalator continuous rides, elevator cabin batches, or stair walking rides.
6. `sink`: a passenger is counted as departed only after vertical service
   finishes.

Important invariant: a passenger must not appear in `sink` unless vertical
service has completed.

## Modeling Rationale

This probe deliberately keeps two model layers visible:

- Pedestrian dynamics: JuPedSim handles walking and collision while passengers
  approach the vertical facility.
- Facility process: Mesa owns queue ordering, elevator batching, escalator ride
  timing, stair throughput, release positions, and service metrics.

This avoids a bad simplification where passengers are teleported from an
approach point into a full-station vertical connector without checking whether
queue capture, batching, and release behavior are coherent by themselves.

## Code Ownership

Main animated probe:

```text
scripts/run_vertical_flow_probe.py
```

Key pieces:

- `VerticalFlowProbeModel`: source, sink, JuPedSim adapter, vertical facility,
  and frame snapshots.
- `vertical_pre_capture_targets()`: fan targets before queue capture.
- `vertical_queue_slots()`: single head slot plus staggered two-column queue.
- `vertical_config()`: probe-specific escalator, elevator, and stair process
  settings. The elevator probe uses a minimum dispatch load before departing, so
  the first early arrival does not immediately consume one full cabin cycle.
- `animation_html_document()`: lightweight debug renderer for the probe.

Existing process-only probe:

```text
scripts/run_vertical_transport_probe.py
```

Use the process-only probe for broad matrix capacity checks. Use the animated
flow probe when the question is whether the source/approach/queue/service/sink
logic looks physically plausible.

Regression tests:

```text
tests/test_vertical_flow_probe.py
tests/test_vertical_transport_probe.py
```

## Demo Command

Use this to generate the currently useful visual probe:

```powershell
python scripts\run_vertical_flow_probe.py `
  --kinds escalator,elevator,stairs `
  --demands 1800 `
  --service-persons 18 `
  --minutes 1 `
  --tick-seconds 1 `
  --drain-seconds 420 `
  --walk-units-per-tick 0.7 `
  --movement-backend jupedsim `
  --jupedsim-iterations-per-tick 20 `
  --arrival-profile burst `
  --quiet
```

Serve the generated animation if no server is already running:

```powershell
python -m http.server 8788 --bind 127.0.0.1 -d output\vertical_flow_probe
```

Open:

```text
http://127.0.0.1:8788/vertical_flow_probe_animation.html
```

If the turnstile probe server is already serving `output\turnstile_flow_probe`
on port 8787, write only the animation HTML into that served directory:

```powershell
python scripts\run_vertical_flow_probe.py `
  --kinds escalator,elevator,stairs `
  --demands 1800 `
  --service-persons 18 `
  --minutes 1 `
  --tick-seconds 1 `
  --drain-seconds 420 `
  --walk-units-per-tick 0.7 `
  --movement-backend jupedsim `
  --jupedsim-iterations-per-tick 20 `
  --arrival-profile burst `
  --html-out output\turnstile_flow_probe\vertical_flow_probe_animation.html `
  --quiet
```

Then open:

```text
http://127.0.0.1:8787/vertical_flow_probe_animation.html
```

Expected visual checks:

- Blue walking passengers fan into the pre-capture zone.
- Yellow queue marks show the ordered queue slots before the facility.
- Purple passengers occupy the facility while being served.
- Elevator runs show cabin batching and `cabins > 0`.
- The side panel shows nonzero `jps steps` for JuPedSim runs.
- `sink` increases only after vertical service completion.

## Stress Command

Use this matrix before relying on vertical behavior in a larger station:

```powershell
python scripts\run_vertical_flow_probe.py `
  --kinds escalator,elevator,stairs `
  --demands 1200,1800,2400 `
  --service-persons 12,18,24 `
  --seeds 1,2,3 `
  --minutes 1 `
  --tick-seconds 1 `
  --drain-seconds 480 `
  --walk-units-per-tick 0.7 `
  --movement-backend jupedsim `
  --jupedsim-iterations-per-tick 20 `
  --arrival-profile burst `
  --output-stem vertical_flow_probe_stress `
  --quiet
```

Generated stress outputs:

```text
output/vertical_flow_probe/vertical_flow_probe_stress.csv
output/vertical_flow_probe/vertical_flow_probe_stress.json
output/vertical_flow_probe/vertical_flow_probe_stress.md
output/vertical_flow_probe/vertical_flow_probe_stress_animation.html
```

The stress run should report:

- `errors = 0`
- `jupedsim_steps > 0` for JuPedSim runs
- `source_persons = sink_persons + unserved_persons`
- elevator `service_persons_max <= 8` for the current probe cabin config
- lower service rates or higher demand should increase queue/wait metrics
- `backlog = 0` only when the configured drain window is intentionally enough

## Acceptance Criteria

Before using this behavior as a building block in the full station:

1. Run the focused tests:

   ```powershell
   python -m unittest tests.test_vertical_flow_probe
   ```

2. Run the process-only vertical tests:

   ```powershell
   python -m unittest tests.test_vertical_transport_probe
   ```

3. Run the full test suite after shared facility changes:

   ```powershell
   python -m unittest discover -s tests
   ```

4. Regenerate the demo animation and inspect the visual behavior.

5. Run the stress matrix and inspect worst cases:

   - `worst_queue_persons_max`
   - `p95_queue_wait_seconds`
   - `p95_system_seconds`
   - `departed_cabins`
   - `worst_unserved_persons`

## Full-Station Integration

The probe does not own production behavior. It validates rules that are then
promoted into the full-station runtime:

- `StationSandboxScenario.elevator_min_dispatch_persons`
- `StationSandboxScenario.elevator_max_dispatch_wait_seconds`
- `layout_graph._build_vertical_config()`
- `ElevatorProcessAgent`
- `visual_demo.mesa_export`

The expected full-station result is that a local elevator/escalator/stairs
region behaves like this probe: passengers approach the vertical facility,
queue, enter service, and appear as a coherent batch or flow in the final
animation. Do not maintain a separate visual-only vertical behavior in the full
station.

## Current Baseline

For the demo command above, the last known baseline was:

```text
source_persons = 30
sink_persons = 30
unserved_persons = 0
escalator queue_persons_max = 16
elevator queue_persons_max = 22
stairs queue_persons_max = 3
elevator first_departure_load_persons = 8
elevator departed_cabins = 4
worst_service_persons_max = 10
jupedsim_steps = 3209
```

## How To Extend

When adding or changing a vertical facility behavior, keep the same pattern:

1. Define the smallest source/process/sink loop.
2. Keep the movement backend and facility service boundary explicit.
3. Add animation fields that expose the internal state being validated.
4. Add focused tests for the discovered bug or invariant.
5. Add a stress command with enough seeds to catch stochastic regressions.

Do not start from full-station composition when the vertical behavior itself is
still under inspection.
