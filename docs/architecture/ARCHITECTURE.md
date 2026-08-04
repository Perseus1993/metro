# Metro Station Architecture

## Status

This document defines the implemented boundary for the official station simulation runtime.
Production implementation lives in the `metro_station` distribution. The former
`sandbox.metro_station_sandbox` namespace contains forwarding compatibility modules only.

## Dependency direction

Dependencies point inward:

```text
interfaces / experiments / adapters
                 |
                 v
             application
                 |
                 v
               domain
```

- `domain` owns Goal, Journey, station-topology, facility, and passenger concepts. It does
  not import Mesa, JuPedSim, Shapely, visualization, experiment, or web modules.
- `application` owns use cases, compilation pipelines, simulation coordination, ports, and
  versioned output contracts. It depends on `domain`, never concrete adapters.
- `adapters` implement application ports for Mesa, JuPedSim, geometry, data loading, and
  visualization.
- `interfaces` parse CLI or HTTP input and invoke application use cases.
- `experiments` consume the public application API; they are not part of the production
  runtime.
- `bootstrap` is the composition root and is the only place that wires concrete adapters to
  application ports.

## Runtime invariants

1. Goal Graph is the only strategic behavior authority.
2. Only a Goal completion command may authorize a passenger terminal event.
3. Station topology is compiled from explicit design connections and facility service edges.
4. Visualization consumes versioned snapshots and never supplies simulation truth.
5. Tick ordering, random draw ordering, person conservation, and fixed-seed semantic
   fingerprints are compatibility contracts.
6. A migration change either moves code or changes behavior, never both in one review unit.
7. Strategy selection, evacuation routing, movement, and experiment optimization use separate
   extension contracts; V0.2 exposes only evacuation routing as a third-party plugin (ADR-007).

## Enforcement

Import Linter contracts in `pyproject.toml` prevent new reverse dependencies. Existing
exceptions are listed in `dependency-rules.md`; each exception has a removal phase and no
new exception may be added without an ADR.

Every architecture change must pass:

```powershell
uv sync --locked --all-extras --all-packages
uv run --no-sync ruff check apps experiments packages quality sandbox scripts src tests
uv run --no-sync lint-imports
uv run --no-sync pytest -q
uv run --no-sync python scripts/run_layout_acceptance.py --tier smoke
```

Pyright strict gating is introduced package by package. The pre-migration repository baseline
contains 914 errors across production, scripts, tests, and unresolved optional dependencies;
therefore CI must not hide them with a global suppression file. The new pure domain package
starts at zero errors in phase 3, and subsequent migrated packages join that zero-error gate.

## Target package layout

```text
packages/metro_station/src/metro_station/
  domain/
  application/
  adapters/
    simulation/
  interfaces/
  bootstrap.py
apps/
experiments/metro_station_experiments/
quality/metro_station_testkit/
quality/metro_station_acceptance/
tests/
```

## Physical package result

The workspace is split into independently buildable distributions:

```text
src/metro_data_warehouse/                 # reusable warehouse library
packages/metro_station/                   # official production runtime
apps/station_designer/                    # design UI
apps/station_visualizer/                  # renderer and replay UI
experiments/metro_station_experiments/    # experiment runners and analysis
quality/metro_station_testkit/            # deterministic probes
quality/metro_station_acceptance/         # acceptance harnesses
sandbox/metro_station_sandbox/            # forwarding compatibility namespace
```

The official package is forbidden from importing the legacy namespace, repository scripts,
testkit, acceptance, experiments, or visualization applications. Experiment code invokes the
application simulation use case rather than constructing Mesa models directly.

See the ADRs in this directory for decisions that must survive the physical package move.
