# Dependency Rules and Migration Exceptions

## Permanent rules

1. Goal and Journey domain modules do not import runtime, agents, facilities, movement,
   station compilation, design UI, experiments, or visualization.
2. Design schema validation does not compile a `StationGraph`.
3. Production runtime does not import experiment or visualization modules.
4. Visualization does not import experiment analysis.
5. Experiments call `metro_station.application.simulation` and do not construct
   `MetroStationModel` directly.
6. A dependency exception requires an ADR, owner, removal phase, and regression test.

The `metro_station.domain` rule includes indirect imports and explicitly forbids the legacy
`sandbox` package plus Mesa, JuPedSim, Shapely, NumPy, pandas, NetworkX. New domain modules must
therefore remain importable with the Python standard library alone.

## Compatibility namespace

`sandbox.metro_station_sandbox` contains forwarding modules for legacy imports. The official
package never imports that namespace. Import Linter's unmatched-ignore check remains enabled so
a future exception cannot silently outlive its dependency.

## Review rule

Temporary exceptions may be removed or narrowed. Adding or broadening one fails architecture
review unless a new ADR explains why the target boundary must change.
