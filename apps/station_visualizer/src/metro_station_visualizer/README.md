# Metro Station Visual Demo

This package contains the station geometry, ABM/JuPedSim passenger tracks, and the standalone HTML Canvas visual demo.

- `config.py`: shared paths, canvas scale, simulation timing.
- `facilities.py`: single source of truth for visual facility boxes and door/queue anchor points.
- `layout.py`: station floor, obstacle, connector, facility, and control-point geometry.
- `geometry.py`: station walkable geometry and coordinate transforms.
- `specs.py`: route specs, native facility queue specs, and route-to-facility bindings.
- `process_model.py`: facility-process grouping used by the generator so entry gates, exit gates, vertical transport, and train doors share one queue/service vocabulary.
- `queue_runtime.py`: queue slot generation, visual targeting, service distance, queue payloads, and audited virtual queue state.
- `floor_field.py`: cached walkable grid and multi-source floor-field solver for fast static and dynamic potential fields.
- `region_flow.py`: compiles region-to-facility capture flows into portal bands before they become JuPedSim stages.
- `field_routing.py`: queue attractiveness field scoring for stalled targeters, combining reachability, distance, load, service speed, and switching inertia.
- `generate_jps_tracks.py`: compatibility CLI wrapper for building `assets/passenger_tracks_jps.js`.
- `tracks/`: JuPedSim track generation internals split by responsibility: builder, CLI, stage/waypoint helpers, entry and alighting journeys, queues, replanning, and debug payloads.
- `analyze_sim_debug.py`: reads the raw simulation debug JSON and reports likely stuck windows without using the HTML renderer.
- `animation_demo.html`: standalone HTML Canvas renderer.
- `record_visual_demo.py`: Playwright + ffmpeg recorder for MP4 export.
- `generate_passenger_sprite_assets.py`: builds the passenger sprite atlas and frame metadata used by `animation_demo.html`.
- `assets/station_base.png`: legacy image2 background kept only as a visual reference; the demo now renders the base from geometry.
- `assets/facility_sprite_sheet.png`: saved facility sprite sheet source asset.
- `assets/passenger_sprite_atlas.png` and `assets/passenger_sprite_atlas.json`: 10 passenger types, walk/queue actions, four directions, and four frames per action/direction.
- `assets/passenger_sprite_library.js`: lightweight Canvas runtime for selecting passenger sprite frames from track speed, direction, and diagnostic state.
- `assets/passenger_style_board_ai.png`: AI-generated style reference board for future handoff or replacement art.

Official run:

```powershell
python -m sandbox.metro_station_sandbox.app
```

Module-level tools:

```powershell
python -m metro_station_visualizer.generate_jps_tracks
python -m metro_station_visualizer.analyze_sim_debug
python -m metro_station_visualizer.render_geometry_preview
python -m metro_station_visualizer.record_visual_demo --start-sec 4 --duration-sec 42
python -m metro_station_visualizer.generate_passenger_sprite_assets
```

The generated track payload includes `layout`, `queue_layouts`, `native_queue_model`, `queue_samples`, and `clearance_audit` so geometry, queues, queue length, targeting pressure, and final evacuation status can be inspected separately from the rendered animation. The generator also writes `output/visual_demo_sim_debug.json`, a renderer-free trace of raw JuPedSim agent positions, named stage ids, stage radii, facility queue states, geometry reachability diagnostics, service releases, and the same clearance audit.
Passenger tracks are sampled directly from JuPedSim. The station process is modeled as continuous journeys, so the exporter no longer stitches release segments, respawns passengers between facilities, or applies a final speed-smoothing pass.
The demo runs long enough to include the next train-door service window after the main entrance pulse reaches the platform.
The renderer draws the station base from generated geometry rather than from `station_base.png`, and reads the elevator box from the same payload as the native elevator queue.
Boarding passengers use native JuPedSim queue stages whose service release continues into screen-door, vestibule, and train-exit stages inside the same passenger journey.
Alighting passengers spawn at open train doors and stay in a continuous JuPedSim journey through the upward facility queue, exit-gate queue, and station exit.
Initial demand now starts only at the two B1 entrances, passes through six single-column native gate queues with realistic turnstile service timing and fanned queue tails, then continues to down-escalator or native batch elevator queues and B2 train-door queues.
Passenger arrivals are generated as small bursty groups with per-agent radius, time-gap, walking speed, and render-motion variation. Queue slots keep their service order but include deterministic micro-jitter so waiting passengers do not appear as perfectly even particles.
The renderer samples raw JuPedSim positions and draws facility-level targets: active passengers point at the selected discrete queue tail, without substituting synthetic queue positions.
Target choice is staged at decision points: entrance passengers choose a gate with JuPedSim least-targeted transitions near the gate area, then continue through escalator or native batch elevator branches to platform train-door queues; alighting passengers choose exit gates after their upward facility. Facility service releases native JuPedSim enqueued agents first, then audited virtual-queue agents that reached a valid capture area, so unresolved targeters remain visible diagnostics instead of being silently released by a visual patch.
Stage diagnostics make the three failure modes explicit: geometry connectivity checks every waypoint/queue slot against walkable components, queue reachability reports queue stages and stuck targeters separately from enqueued service, and decision radii are emitted per named decision stage.
Current journey tuning uses wider corridor-style radii for alighting merge stages, right-entry gate approaches, boarding door zones, and station exits, plus extra native queue apron slots for gate/escalator reachability; these remain JuPedSim stages/queues rather than sampled trajectory patches.
Region-to-facility movement should go through portal/capture flows where local congestion matters. The right-entry down-transfer path and alighting exit-gate choice compile source regions to queue capture bands before entering native queue stages, while entry-gate service releases first pass through a narrow post-gate portal before widening into corridor bands. Elevator approaches are modeled as entrance bands rather than a single hard point.
Long-lived queue targeters are evaluated by a queue attractiveness field. Boarding-door queues can now switch to a more attractive adjacent door when grid distance, density, load, and service speed make the alternative clearly better; entry and exit gates remain audit-only so paid/unpaid barriers are not bypassed by replanning. Candidate costs and switch decisions are written to the debug log.
Grid floor fields are also intended for the next routing layer: geometry adjacency is cached once, dynamic density penalties are refreshed from current agent positions, and per-target fields can then be recomputed in milliseconds without re-running Shapely wall checks.
Fare barriers are part of the blocking station geometry, with openings only at gate boxes. Passenger positions are not render-snapped to queue slots; the visual layer keeps JuPedSim coordinates and uses queue targets only as markers.
Development protocol: any degraded or soft-release path must be visible in audit output. It should report how many agents used it, which facility/stage it touched, and whether the run cleared all generated demand before `CLEARANCE_MAX_DURATION`; silent degradation is treated as a bug, not a convenience.
