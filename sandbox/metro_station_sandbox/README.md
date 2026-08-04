# Metro Station Sandbox

Subgoal 1 prototype: a single-station passenger-flow sandbox.

Passenger behavior semantics are defined in
[`PASSENGER_BEHAVIOR_MODEL.md`](PASSENGER_BEHAVIOR_MODEL.md): passenger goals
are region-to-region, while queues, facilities, service, and replanning are
compiled behavior actions.

Micro-scene validation is recorded in
[`TURNSTILE_FLOW_PROBE.md`](TURNSTILE_FLOW_PROBE.md) and
[`VERTICAL_FLOW_PROBE.md`](VERTICAL_FLOW_PROBE.md). Use these probes before
folding gate or vertical queue/service changes back into full-station scenarios.

Module layout:

- `design/`: editable `StationDesignDocument`, topology templates, validation, and React Flow editor adapter.
- `design_inspector/`: isolated React Flow design inspector with live validation and graph diagnostics.
- `station/`: design compilation and station topology: `StationGraph`, `LayoutGraph`, `RuntimeStationLayout`, geometry safety, scenario config, route catalog.
- `planning/`: passenger intent/state/action model, graph-aware plan factory, progress monitoring, and selection helpers.
- `agents/`: Mesa agent classes split by domain: passenger behavior, platform/train transit resources, admin staff guidance, and shared base classes.
- `facilities/`: OOP facility process model, including abstract `FacilityProcessAgent` plus gates, escalators, elevators, stairs, and boarding doors.
- `movement/`: movement backend request/result interface and JuPedSim adapter.
- `runtime/`: `MetroStationModel`, demand scheduling, snapshots, metrics, audit, and stress-run helpers.
- `visual_demo/`: visualization adapter and retained high-fidelity demo renderer.
- The package root `__init__.py` re-exports common public classes. New module imports should target the owning subpackage directly.

Mesa owns the station process:

- passenger agents
- gate/security service agents
- platform waiting and boarding resource agents
- train arrival, dwell, boarding capacity, departure
- metric collection

ABM entities:

- `PassengerAgent`: one passenger by default, with explicit intent, route plan, state, and current goal.
- `FacilityProcessAgent`: shared queue/service/release process for entry gates, exit gates, vertical transport, and train doors.
- `PlatformAgent`: active platform resource with waiting passengers and platform capacity, keyed by `platform_id`.
- `TrainAgent`: periodic train event with dwell time and capacity, keyed by `line_id`, `direction`, and `platform_id`.

The intended ownership boundary is:

- `LayoutGraph`: where things are and how major station nodes connect.
- `StationGraph`: graph routing bridge from editable design documents to Mesa simulation facilities/routes.
- `JourneyGraph` / `PassengerGoalRuntime`: the active strategic state machine for
  passenger intent, late facility choice, commitment, waiting, replanning, and
  terminal completion. Each passenger owns an independent runtime.
- `AgentPlan`: a temporary physical-goal adapter. It contains no strategic
  facility-selection actions; Graph decisions are authoritative.
- `JourneyGraphCatalogCompiler`: derives the number of vertical-transfer stages
  from the compiled station graph for each intent.
- `GoalFacilitySelector`: the pure Goal Runtime policy for choosing among the
  observations supplied at a physical decision region.
- `AdminAgent`: optional staff/admin agent that patrols the station and reports
  operational facts without directly mutating passenger Goal State.
- `FacilityProcessAgent`: queue geometry, service rules, release route, and capacity gates.
- `TrainAgent`/`PlatformAgent`/boarding-door facilities: bound through `platform_id`, so multiple lines and directions can coexist without every door reading `model.train`.
- `PassengerAgent`: walking toward its current goal and applying plan actions; it should not own station journey topology.
- `MovementBackend`: how an agent physically advances toward a target.
- `visual_demo/mesa_export.py`: the only official visualization export boundary; it consumes Mesa snapshots and writes `window.JPS_TRACKS`.
- `JuPedSimAdapter`: local walking/collision adapter only, not station business logic.
- `audit.py`: structured audit sink for diagnostic events.

Current architecture guarantees:

- `StationGraph` uses explicit `DesignConnection` records plus service edges
  derived from facilities as the authoritative process graph.
- Built-in design templates emit standard graph ports and explicit access
  connections for entrances, gates, vertical connectors, and platform edges.
- Gate `service` and `release` ports are directional, so template gate approach
  and release connections compile as directed graph edges.
- Built-in templates should compile without `graph.connection_endpoint_inferred`
  or `graph.same_level_access_fallback` diagnostics.
- Same-level walkable access edges are compatibility fallback edges. They are
  tagged as `walkable_access_fallback` and emitted through graph compile diagnostics.
- Missing explicit process connections are validation errors.
- Passenger routing is level-aware, so overlapping vertical connector nodes on different levels do not alias each other.
- Platform intent is explicit through `line_id`, `direction`, and `platform_id`;
  boarding-door commitment is made by Goal Runtime at the boarding decision region.

Official runtime:

- `app.py`: the official entry point. It runs `MetroStationModel` with strict
  JuPedSim movement, then exports the result as an `animation_demo.html`
  payload.
- `visual_demo/mesa_export.py`: converts Mesa frame snapshots into
  `window.JPS_TRACKS`, the data format consumed by the visual demo renderer.
- `visual_demo/animation_demo.html`: the only user-facing renderer. It plays
  `visual_demo/assets/passenger_tracks_jps.js`.
- `design_inspector/inspector.html`: a sandbox-only station editor/diagnostic
  surface. It uses React Flow for canvas state, then posts nodes/edges back to
  Python so `StationDesignDocument` validation and `StationGraph` compilation
  remain authoritative.
- `visual_demo/tracks/`: retained as the high-fidelity continuous JuPedSim
  reference generator and diagnostic surface.

Run:

```powershell
python -m sandbox.metro_station_sandbox.app
```

Run with active Goal Graph planning and an external graph catalog:

```powershell
python -m sandbox.metro_station_sandbox.app `
  --goal-graph-mode active `
  --goal-graph-config sandbox/metro_station_sandbox/config/goal_graph_catalog.json
```

Regenerate the topology-aware default catalog and run the 300-person acceptance:

```powershell
python -m scripts.generate_goal_graph_catalog --design-template visual_demo_station
python -m scripts.run_goal_graph_large_acceptance --seed 42
```

Run the shared maturity gate across all four built-in layouts:

```powershell
python scripts/run_layout_acceptance.py --tier smoke
python scripts/run_layout_acceptance.py --tier nightly
python scripts/run_layout_acceptance.py --tier release
```

All tiers use the same contract and do not skip unsupported scenarios. The
release tier freezes seeds `41`, `42`, and `43`, runs 300-person mixed normal
demand plus 30-person evacuation for every layout, runs all five operational
recovery scenarios, repeats one seed for a deterministic semantic fingerprint,
and requires full physical/facility/movement/Goal Graph clearance. JSON and
Markdown evidence are written to `output/layout_acceptance/`.

| Tier | Purpose | Seeds | Gate |
|---|---|---:|---|
| `smoke` | pull request feedback | 42 | all layouts, four journeys, five disruptions |
| `nightly` | repeated medium load | 41, 42, 43 | same matrix with higher demand |
| `release` | maturity decision | 41, 42, 43 | 300-person load, clearance, trajectories, parity, determinism |

The four layout IDs covered by the contract are
`two_level_island_platform`, `three_level_transfer`,
`single_level_terminal`, and `visual_demo_station`. CI runs the smoke tier on
changes, the nightly tier on schedule, and exposes the release tier through
manual dispatch.

Goal Graph is the only behavior runtime. Old scenario options are upgraded by
the migration boundary and do not enable a second execution path. In the production
Event -> GoalStateMachine -> CommandExecutor loop, commitment is delayed until
the physical decision region, facilities require a
matching Goal commitment before queue or service entry, and only
`COMPLETE_JOURNEY` may create a passenger terminal event.

Run and serve the visual demo locally:

```powershell
python -m sandbox.metro_station_sandbox.app --serve
```

Open:

```text
http://127.0.0.1:8765/animation_demo.html
```

Run and serve the station design inspector:

```powershell
python -m sandbox.metro_station_sandbox.app --serve-inspector --port 8766
```

Open:

```text
http://127.0.0.1:8766/inspector.html
```

To build a station from an empty shell:

1. Start from a one-click preset (compact single-level, standard two-level,
   compact transfer, standard three-level transfer, or high-volume hub), or
   complete the blocking custom wizard: choose one to three levels, choose a
   regular or transfer station, then choose the entrance and total gate counts.
   Presets and custom setups use the same generator and remain fully editable.
   The gate total is split between entry and exit gates (entry gets the extra
   gate when the total is odd).
2. The editor automatically places entrances, both gate directions, one or two
   line platforms, plus up/down escalators, stairs, and an accessible elevator
   for every required floor transition. Every generated facility remains
   draggable and resizable. Use the component cards to add more vertical routes,
   equipment, or obstacles; a
   card click finds a valid position, while dragging gives exact control.
3. Keep facilities inside the floor boundary and separated by the displayed
   clearance rules, then choose **Generate station**. Generation derives queues,
   semantic ports, walk access, and vertical graph connections; it never invents
   a missing strategic facility.
4. Click a passenger-flow card to bind it automatically, or drag **Entry →
   board** onto an entrance and **Train → exit** / **Platform transfer** onto a
   platform. Select a transfer flow to choose its destination platform and edit
   its hourly rate. A generated custom station cannot run without at least one
   explicit flow. The Operations panel controls the remaining bounded parameters.
5. Run **Simulate** only after the compile status is green. Invalid geometry,
   missing facilities, ambiguous demand, excessive rates, or broken graph
   connections disable simulation and return stable diagnostics. A valid run
   uses the Goal Graph runtime with the JuPedSim movement backend.

The editor sends ordinary React Flow state to the server, but domain generation
and validation remain in Python. `StationDesignDocument` and `StationGraph` are
therefore authoritative; visual nodes cannot directly mutate Goal State or
bypass operation limits.

Every meaningful editor action is also written to a session-correlated JSONL
debug log at `output/station_designer_debug.jsonl`. It includes wizard choices,
facility and demand changes, final drag/resize positions, compile request
snapshots, complete generated document/graph responses, validation diagnostics,
simulation parameters, queued job IDs, and asynchronous simulation results.
The **操作与生成日志** section in the right panel can switch between the current
browser session and all sessions, refresh, copy the visible records, or export
the JSONL file. Client sequence numbers and server request IDs preserve ordering
and connect an action to its generated result. The log rotates to
`station_designer_debug.jsonl.1` after 100 MiB.

The app writes:

```powershell
apps/station_visualizer/src/metro_station_visualizer/assets/passenger_tracks_jps.js
```

The generated track payload includes scenario metadata, train service timing,
layout, queue layouts, Mesa passenger tracks, queue samples, train samples,
final metrics, and JuPedSim backend counters. The HTML renderer is fixed;
rerunning the app updates the data file it plays.

Unit tests:

```powershell
python -m unittest discover -s tests
```

Run a threshold-gated stress matrix:

```powershell
python -m scripts.run_metro_stress_matrix `
  --pairs 4000:2000,6000:3000 `
  --seeds 41,42,43 `
  --minutes 15 `
  --demand-minutes 10 `
  --min-completion-rate 0.95 `
  --max-final-station-persons 100
```

The stress command returns a non-zero exit code when a run errors or a supplied
threshold fails. The experiment runner also returns non-zero for trajectory
failures; add `--fail-on-warn` for a strict release candidate. Configuration
readiness can be checked with
`experiment.acceptance.assess_production_scenario()` before a production run.

Run a production-gated candidate explicitly:

```powershell
python -m scripts.run_metro_stress_matrix `
  --pairs 4800:2400 `
  --seeds 41,42,43 `
  --minutes 24 `
  --demand-minutes 3 `
  --movement-backend batched_jupedsim `
  --clock-mode physical `
  --goal-graph-mode active `
  --calibration-status validated `
  --calibration-profile-id station_candidate_v1 `
  --calibration-dataset-id calibration_day `
  --validation-dataset-id validation_day `
  --production-acceptance `
  --min-completion-rate 0.95 `
  --max-final-station-persons 20
```

Calibration identifiers are evidence metadata, not calibration itself. Mark a
profile as `validated` only after fitting against one dataset and checking the
frozen parameters against an independent dataset.

Run normalized geometry boundary probes against production clock and planning:

```powershell
python -m scripts.run_metro_boundary_hack_agent `
  --clock-mode physical `
  --goal-graph-mode active `
  --epsilon-boundary-samples 4 `
  --boundary-epsilon 0.05 `
  --minutes 12
```

Each epsilon case records the raw point, its `inside_epsilon`, `on_boundary`,
or `outside_epsilon` relation, the normalized safe point, and normalization
distance before running the complete passenger journey.

Inject static facility and train-service faults with repeatable CLI inputs:

```powershell
python -m scripts.run_metro_stress_matrix `
  --pairs 2400:1200 `
  --clock-mode physical `
  --goal-graph-mode active `
  --disable-facility entry_gate:gate_bank_a:lane_1 `
  --disable-facility vertical:down_escalator_a:down:b1_concourse:b2_platform `
  --initial-train-offset-seconds 600 `
  --train-headway-seconds 240 `
  --train-capacity-persons 30
```

Unknown facility ids fail at startup. Disabled facilities remain visible as
`state=disabled` in final service evidence, including their cumulative served
persons. Train diagnostics record maximum current load, maximum departed load,
and final departure count so capacity faults can be audited.

Inject a facility closure and recovery during the run:

```powershell
python -m scripts.run_metro_stress_matrix `
  --pairs 2400:1200 `
  --minutes 18 `
  --demand-minutes 3 `
  --clock-mode physical `
  --goal-graph-mode active `
  --facility-event 60:disable:entry_gate:gate_bank_a:lane_1 `
  --facility-event 180:enable:entry_gate:gate_bank_a:lane_1 `
  --min-completion-rate 0.95
```

Dynamic events must be time ordered, align exactly with `--tick-seconds`, and
alternate `disable` then `enable` for each facility. Queued passengers attempt
an immediate same-stage replan when a facility closes; already-started service
is allowed to finish. The report records every scheduled/applied transition,
the queue present at closure, replan count, and any service that incorrectly
started inside a disabled interval. Such a service violation always fails the
stress acceptance decision.

Suspend and recover scheduled train service for one platform:

```powershell
python -m scripts.run_metro_stress_matrix `
  --pairs 2400:1200 `
  --minutes 24 `
  --demand-minutes 3 `
  --clock-mode physical `
  --goal-graph-mode active `
  --train-event 60:suspend:platform:default:down `
  --train-event 600:resume:platform:default:down `
  --min-completion-rate 0.95
```

A suspension lets a train already dwelling at the platform finish its current
stop, then cancels each later scheduled arrival until recovery. Recovery does
not create an unscheduled train; service resumes on the next timetable arrival.
Reports retain applied suspension events, each cancelled arrival, cumulative
cancellation count, next scheduled arrival, and any invalid arrival while the
platform service was suspended.

Alighting demand is conserved across cancelled arrivals: it remains as upstream
deferred demand and is released by the first recovered train. Completion rate is
calculated against scheduled demand rather than only passengers that happened to
spawn, and the report exposes deferred demand plus any accounting difference.

For an in-service vertical-equipment fault, schedule the ordinary facility event
inside a known active-service window. A disabled elevator rejects new boarding;
boarding, moving, and empty-return phases freeze until recovery, while an
already-open unloading phase completes safe unloading. A stopped escalator
rejects new riders but lets existing riders walk off at stair speed. Reports
include active persons at the stop, impacted persons, outage person-seconds, and
passengers still stranded in disabled equipment. Any final stranded passenger
fails acceptance.

Use `--elevator-preference-share` and `--stairs-preference-share` when a stress
case must exercise a specific vertical mode. Preference alone does not guarantee
selection when live queue costs favor another facility; disable alternatives
explicitly for a fault-isolation experiment.

Run a combined-emergency evacuation matrix with explicit safety gates:

```powershell
python -m scripts.run_metro_emergency_matrix `
  --populations 60,120,240 `
  --seeds 41,42,43 `
  --minutes 15 `
  --production-acceptance `
  --calibration-status validated `
  --calibration-dataset-id calibration_day `
  --validation-dataset-id validation_day `
  --min-completion-rate 1 `
  --max-clearance-seconds 800 `
  --max-final-station-persons 0 `
  --max-local-density-persons-m2 6 `
  --facility-event 0:disable:exit_gate:exit_gate_bank_a:lane_1 `
  --facility-event 0:disable:vertical:elevator_a:up:b2_platform:b1_concourse `
  --facility-event 60:disable:vertical:up_escalator_a:up:b2_platform:b1_concourse
```

The emergency runner reports T90/T95/T99, clearance time, exact population
accounting, local-neighborhood density, density exposure, fault evidence, and
final stranded passengers. Zero-population cases are valid exact-boundary tests.
Fully blocked or overloaded cases are expected to return a non-zero exit code
with explicit failed gates. Density limits are configurable project inputs; the
example value is a simulation candidate and is not a substitute for approval by
the station operator or fire-safety authority.

Run statistical, sensitivity, long-soak, calibration, and final release gates:

```powershell
python -m scripts.run_metro_emergency_matrix --populations 60 --seeds 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30 --resume
python -m scripts.analyze_metro_reliability output/metro_emergency_matrix/metro_emergency_matrix.json
python -m scripts.run_metro_emergency_sensitivity
python -m scripts.run_metro_soak --minutes 30
python -m scripts.validate_metro_calibration --simulated simulation.json --observed independent_observations.csv --calibration-dataset-id calibration_day --validation-dataset-id validation_day
python -m scripts.assess_metro_release --emergency emergency.json --reliability reliability.json --sensitivity sensitivity.json --performance soak.json --calibration calibration.json
```

Reliability requires at least 30 seeds for every required population. Resume
files are protected by a configuration fingerprint, so completed cells are only
reused when the scenario configuration is identical. Sensitivity fails when a
material parameter sweep produces no observable change in either clearance or
peak density; zero response is treated as missing model influence, not proof of
robustness.

The soak runner uses a deliberately blocked egress to retain passengers for the
full requested horizon and records frame completeness, wall time, simulated to
wall-time ratio, and traced Python memory. Calibration validation needs matched
real observations and separate calibration/validation dataset IDs. Missing
files produce `blocked`, and metadata alone cannot satisfy the release gate.
The final release assessment remains blocked until every evidence component and
the operator/fire-authority density threshold approval pass.

JuPedSim walking speed is configured explicitly with
`--jupedsim-desired-speed-mps`. The density slowdown coefficient now changes
each active JuPedSim agent's desired speed; it is no longer report-only data.
Sensitivity scenarios isolate a single gate or vertical route when necessary so
the parameter under test is actually exercised.

Passengers that reach a facility decision with no available option enter an
explicit choosing/wait state. They do not repeatedly run walking physics while
stationary, and they wake automatically when a matching facility recovers. This
behavior is covered by fully blocked and recovery tests and is required for
long-soak performance.

Emergency outputs carry a model evidence version in addition to the scenario
configuration fingerprint. Resume and final release assessment reject stale
evidence after behavior changes. Parallel seed chunks may be merged with
`scripts.merge_metro_emergency_evidence` only when model versions and
configuration fingerprints match and all run IDs are unique.

The current v4 candidate completes 60-minute blocked-egress soak evidence at
720/720 frames with population accounting intact. Reliability has 30 seeds at
60, 120, and 240 persons. The 240-person group still blocks release because two
seeds exceed the candidate 6.0 persons/m2 density limit in the B2 platform
vertical-egress convergence area. Do not raise the limit or alter initial crowd
placement without independent observations and operator/fire-safety approval.
