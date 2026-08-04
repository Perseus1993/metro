# ADR-007: Separate Strategy, Routing, Movement, and Optimization Extensions

- Status: Accepted

## Context

The V0.2 product direction allows students and researchers to compare evacuation algorithms.
Existing code already has a pure facility-selection protocol, internal station-graph routing, an
injectable movement backend, and experiment runners. These extension points operate at different
frequencies and own different decisions. Exposing them through one generic plugin would let a
single implementation change goals, paths, physical movement, and experiment plans, making paired
comparison and failure attribution unreliable.

## Decision

Define four independent extension families. They have separate contracts, registries, versioning,
test kits, and runtime budgets. There is no generic `AlgorithmPlugin` interface.

### Strategy selection policy

Chooses one facility, such as an exit, stair, or escalator, from an observed candidate set. It
receives decision facts and returns a facility identifier, score, and reason. It cannot construct a
path, move an agent, or schedule experiments. The existing `GoalFacilitySelector` is the internal
baseline for this boundary.

### Evacuation routing plugin

Builds a global route over a versioned topology snapshot. It receives an origin, destination,
current simulation time, closures, passenger-group facts, algorithm seed, and immutable topology.
It returns ordered node/edge identifiers, cost, status, and diagnostics. It cannot choose a
different strategic destination or update physical positions.

V0.2 productizes only this extension family as `evacuation-routing/v1`.

### Movement model plugin

Advances local physical state using positions, neighbors, walkable geometry, desired velocity, and
the physical time step. It returns next physical states and collision/constraint diagnostics. It
cannot select facilities, compute an experiment matrix, or depend on Mesa agent objects in a future
external contract. The current `MovementBackend` remains internal until a framework-independent
port is designed.

### Experiment optimization plugin

Generates and ranks control plans across many simulation evaluations. It receives a parameter
space, constraints, objective definitions, evaluation budget, and a controlled evaluation callback.
It returns ranked plans, trial history, and a stopping reason. It cannot mutate a running
simulation. This family is a later option and is not part of V0.2.

## V0.2 routing protocol boundary

- The plugin manifest uses `algorithm-plugin/v1` and declares `kind=evacuation_routing`, plugin ID,
  plugin version, API version, entry point, parameter schema, and declared capabilities.
- Requests and responses contain JSON-compatible, versioned application contracts; domain and
  application code never imports plugin implementation modules.
- The application layer owns validation, deterministic seed assignment, compatibility checks, and
  decision-log contracts. Concrete process transport belongs to an adapter.
- The plugin host runs each plugin outside the simulation process, validates every response, applies
  per-request/per-run timeouts, captures stderr and exit state, and terminates child processes.
- A plugin failure affects only its run. Batch execution records `failed` or `partial` and preserves
  baseline and completed evidence.
- Every run records plugin ID/version, API version, canonical parameters, request count, compute
  duration, failure status, and a reference to decision logs.
- Process isolation protects batch integrity from crashes and timeouts. It is not a security sandbox;
  V0.2 supports reviewed local code, not arbitrary untrusted plugins.

## Dependency placement

- Stable manifests, routing request/response contracts, and the routing port live in
  `packages/metro_station` domain/application layers and remain framework independent.
- Built-in routing, JSON process transport, worker lifecycle, topology serialization, and runtime
  integration are adapters wired by the composition root.
- The designer configures application use cases and never imports a plugin directly.
- Experiments consume the same application contract and may not maintain a second plugin protocol.
- Reports and replay consume versioned decision/event logs; they do not recompute routing truth.

## Consequences

- Paired experiments can attribute differences to the declared algorithm layer.
- Plugin compatibility and failure behavior can be tested without Mesa or the browser.
- Existing internal selectors and movement backends are not accidentally frozen as public SDKs.
- V0.2 scope is smaller because only routing receives a third-party SDK.
- Supporting a future movement or optimization SDK requires a separate ADR and release evidence.
