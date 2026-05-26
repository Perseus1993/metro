# Metro Station Sandbox

Subgoal 1 prototype: a single-station passenger-flow sandbox.

Passenger behavior semantics are defined in
[`PASSENGER_BEHAVIOR_MODEL.md`](PASSENGER_BEHAVIOR_MODEL.md): passenger goals
are region-to-region, while queues, facilities, service, and replanning are
compiled behavior actions.

Layout-design direction:

- `design/`: editable station design document model for topology templates, level constraints, draggable facilities, queue geometry, validation, and future React Flow editor projection.
- `station_graph.py`: compiles `StationDesignDocument` into weighted graph nodes/edges for simulation routing.
- `plan_factory.py`: builds graph-aware `AgentPlan` instances, including repeated vertical-transfer stages for deeper station templates.
- `design/validation.py`: validates explicit graph reachability; missing walk connections are errors instead of being patched by geometry.
- `visual_demo/layout.py`: current downstream geometry payload used by the canvas/JuPedSim demo.
- The design document is intended to become the source of truth; React Flow should be treated as an editor adapter rather than simulation data.
- `layout_graph.py`: derives named station nodes, route fragments, and facility processes from `StationGeometry`.
- `facility_process.py`: common facility spec and queue-slot geometry for gates, escalators, elevators, stairs, and train doors.
- `agent_plan.py`: passenger intent, facility chain, current state, and current goal.
- `agent_base.py`: common base types for movable, service, and station-owned agents.
- `facility_choice.py`: strategy hook for choosing facilities; staff/admin guidance should plug in here rather than into `MetroStationModel`.
- `movement_backend.py`: movement engine boundary; JuPedSim owns physical passenger motion while Mesa owns passenger journey logic.

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
- `AgentPlan`: why a passenger is in the station, which facility stage is next, and what action follows a reached route/service state.
- `plan_factory`: derives the number of vertical-transfer stages from the compiled station graph for design-driven scenarios.
- `FacilityChoicePolicy`: how a passenger chooses among candidate facilities, including future staff-guided overrides.
- `AdminAgent`: optional staff/admin agent that patrols the station and drives `StaffGuidedPolicy` facility overrides.
- `FacilityProcessAgent`: queue geometry, service rules, release route, and capacity gates.
- `TrainAgent`/`PlatformAgent`/boarding-door facilities: bound through `platform_id`, so multiple lines and directions can coexist without every door reading `model.train`.
- `PassengerAgent`: walking toward its current goal and applying plan actions; it should not own station journey topology.
- `MovementBackend`: how an agent physically advances toward a target.
- `visual_demo/mesa_export.py`: the only official visualization export boundary; it consumes Mesa snapshots and writes `window.JPS_TRACKS`.
- `JuPedSimAdapter`: local walking/collision adapter only, not station business logic.
- `audit.py`: structured audit sink for diagnostic events.

Current architecture guarantees:

- `StationGraph` only uses explicit `DesignConnection` records plus service edges derived from facilities.
- Same-level walk edges are never inferred from distance. Missing connections are validation errors.
- Passenger routing is level-aware, so overlapping vertical connector nodes on different levels do not alias each other.
- Platform choice is explicit through `CHOOSE_PLATFORM`, then route and boarding-door selection are filtered by `line_id`, `direction`, and `platform_id`.

Official runtime:

- `app.py`: the official entry point. It runs `MetroStationModel` with strict
  JuPedSim movement, then exports the result as an `animation_demo.html`
  payload.
- `visual_demo/mesa_export.py`: converts Mesa frame snapshots into
  `window.JPS_TRACKS`, the data format consumed by the visual demo renderer.
- `visual_demo/animation_demo.html`: the only user-facing renderer. It plays
  `visual_demo/assets/passenger_tracks_jps.js`.
- `visual_demo/tracks/`: retained as the high-fidelity continuous JuPedSim
  reference generator and diagnostic surface.

Run:

```powershell
python -m sandbox.metro_station_sandbox.app
```

Run and serve the visual demo locally:

```powershell
python -m sandbox.metro_station_sandbox.app --serve
```

Open:

```text
http://127.0.0.1:8765/animation_demo.html
```

The app writes:

```powershell
sandbox/metro_station_sandbox/visual_demo/assets/passenger_tracks_jps.js
```

The generated track payload includes scenario metadata, train service timing,
layout, queue layouts, Mesa passenger tracks, queue samples, train samples,
final metrics, and JuPedSim backend counters. The HTML renderer is fixed;
rerunning the app updates the data file it plays.

Unit tests:

```powershell
python -m unittest discover -s tests
```
