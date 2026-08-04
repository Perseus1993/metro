# Passenger Behavior Model

This document is the behavior contract for station simulation work. It keeps
passenger intent separate from the facility and queue mechanics needed to
realize that intent.

## Core Principle

A passenger goal is always region-to-region.

Examples:

- entrance region -> train interior
- train door region -> station exit region
- train door region -> transfer platform region
- platform region -> train interior

The passenger should not be born with a hand-authored sequence of waypoints.
Waypoints, queues, portals, and service stages are planner outputs derived from
the station graph and process model.

## Behavior Layers

```mermaid
flowchart TD
    A["Intent"] --> B["Region goal"]
    B --> C["JourneyGraph + GoalStateMachine"]
    C --> D["GoalCommand"]
    D --> E["Movement engine"]
    D --> F["Facility service"]
    E --> G["Progress monitor"]
    F --> G
    G -->|healthy| H["Continue plan"]
    G -->|stalled fact| I["GoalEvent: PROGRESS_STALLED"]
    I --> C
```

### Goal Graph Authority

In `active` mode, `JourneyGraph` and `GoalStateMachine` are the only strategic
behavior authority. They own the current journey stage, candidate evaluation,
facility commitment, queue/service state, replanning, and completion.

`PassengerAgent` reports physical facts and receives commands. `FacilityProcessAgent`
owns queue and service mechanics. The movement backend owns only physical movement
results. `AgentPlan` remains a temporary physical-route compatibility object and
must not execute `CHOOSE_*` actions for active passengers.

Runtime adapters may emit `GoalEvent` values but may not mutate Goal state.
Command executors may translate `GoalCommand` values into movement or facility
operations but may not select an alternative facility themselves.

### Intent

Intent explains why the passenger exists:

- `enter_and_board`
- `exit_station`
- `transfer`

Intent does not prescribe the exact facility sequence.

### Region Goal

Region goals define source and destination areas:

- `unpaid_concourse` -> `platform:line:direction`
- `train_door:line:direction` -> `station_exit`
- `platform:line_a` -> `platform:line_b`

The planner converts this into a route through the station graph.

### Behavior Commands

In active mode, Goal Runtime emits typed commands:

- `walk_to_region`
- `observe_candidates`
- `select_facility`
- `walk_to_queue_tail`
- `join_queue`
- `wait_in_queue`
- `use_facility`
- `release_to_region`
- `board_train`
- `depart`

`AgentPlan` is not this strategic sequence. It is only a temporary physical
execution compatibility object and contains no `CHOOSE_*` actions. The target
of walking is a region or queue capture area, not an arbitrary decorative point.

## Facility Decomposition

Facilities are portals with service semantics.

Example: elevator

```mermaid
stateDiagram-v2
    [*] --> ApproachLobby
    ApproachLobby --> ChooseQueue
    ChooseQueue --> WalkToQueueTail
    WalkToQueueTail --> WaitInQueue
    WaitInQueue --> EnterCabin: service available
    EnterCabin --> Ride
    Ride --> ExitCabin
    ExitCabin --> ReleaseRegion
    ReleaseRegion --> [*]
```

Example: escalator or stair

```mermaid
stateDiagram-v2
    [*] --> ApproachMergeZone
    ApproachMergeZone --> WalkToQueueTail
    WalkToQueueTail --> WaitInQueue
    WaitInQueue --> TraverseFacility: service slot
    TraverseFacility --> ReleaseRegion
    ReleaseRegion --> [*]
```

Example: gate portal

```mermaid
stateDiagram-v2
    [*] --> ApproachGateBank
    ApproachGateBank --> ChooseGateLane
    ChooseGateLane --> WalkToQueueTail
    WalkToQueueTail --> WaitInQueue
    WaitInQueue --> PassGate: service slot
    PassGate --> PaidOrUnpaidRegion
    PaidOrUnpaidRegion --> [*]
```

## Queue Semantics

Queue behavior has three distinct concepts:

- `targeting`: the passenger is approaching the queue capture area.
- `virtual_queue`: the passenger reached a valid queue capture area and has an
  ordered service token even if the pedestrian engine did not enqueue them.
- `enqueued`: the native pedestrian engine owns the queue order.

Service may release either native `enqueued` agents or audited `virtual_queue`
agents. Both must be visible in debug output.

Agents should not be switched into a queue stage from far away. A queue stage is
reachable only when a nearby queue slot or queue capture area is visible through
walkable geometry.

## Progress Monitor

Every active passenger needs progress checks:

- distance advanced since the last monitor sample,
- time spent in the same stage,
- distance to current region or queue capture area,
- queue wait time after joining a queue,
- service availability for the selected facility.

The monitor must distinguish three cases:

- blocked before queue capture,
- waiting correctly in queue,
- stalled after service or release.

## Replanning

Replanning is allowed, but it must be explicit and audited.

Triggers:

- no progress for a configured time window,
- selected facility queue exceeds a wait threshold,
- selected facility becomes unavailable,
- route to the next region is no longer geometry-reachable.

Allowed replans:

- choose the next best facility of the same stage,
- route to another queue capture zone in the same gate or escalator bank,
- choose another vertical transport if the passenger preference permits it,
- choose another boarding door on the same platform.

Disallowed replans:

- teleporting to a queue stage from outside the capture area,
- crossing a fare barrier without a gate service action,
- switching line or direction unless the intent permits transfer replanning,
- silently suppressing the failed route.

Facility alternatives should be ranked by generalized cost:

```text
cost = walking_time + queue_delay + facility_penalty + congestion_penalty
```

Random tie-breaking is allowed only after cost ranking.

## Implementation Target

The long-term API should look like:

```python
RegionGoal(
    origin="entrance:right",
    destination="platform:line_2:down",
    intent="enter_and_board",
)

BehaviorPlanner.plan(goal, station_graph, process_model)
```

The planner should return typed actions, not hand-authored waypoint chains.
Visual demo waypoints are acceptable only as compiled geometry from regions,
portals, queue layouts, and corridor bands.

## Debug Surface

Each frame or debug sample should expose:

- passenger intent,
- current region,
- current action type,
- target region or facility,
- queue mode: `targeting`, `virtual_queue`, or `enqueued`,
- current facility candidate set,
- progress age,
- last replan reason.

This makes stuck passengers explainable by behavior state instead of by visual
position alone.

Current implementation:

- `planning/goal_graph.py` and `planning/default_goal_state_machine.py` define
  the framework-independent journey and transition authority.
- `runtime/passenger_goal_coordinator.py` runs the production event/command loop,
  while `passenger_goal_command_executor.py` translates commands to existing
  physical routes and facility operations.
- `runtime/goal_parity.py` keeps physical and Goal Graph evidence independent
  for runtime diagnostics and clearance proof.
- `MetroStationModel.snapshot()` emits a `behavior` object for every live
  passenger.
- `planning/progress.py` tracks no-progress windows and emits audited route or
  same-stage facility replans.
- `planning/goal_choice.py` selects facilities only from Goal runtime
  observations; facilities and `PassengerAgent` do not rank alternatives.
- `visual_demo/generate_jps_tracks.py` emits `behavior_action`, `queue_mode`,
  `region_goal`, `current_region`, and `target_region` in each sampled agent
  record and stuck-window report.
