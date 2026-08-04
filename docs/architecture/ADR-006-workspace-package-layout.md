# ADR-006: Split Runtime, Applications, Experiments, and Quality Tooling

- Status: Accepted

## Context

The former `sandbox.metro_station_sandbox` distribution mixed production simulation code,
warehouse access, UI assets, experiments, deterministic probes, and acceptance harnesses. The
official command therefore depended on the legacy monolith and the physical layout did not match
the documented dependency direction.

## Decision

Use independently buildable workspace distributions:

- `metro-data-warehouse` owns reusable data access and network/POI code.
- `metro-station` owns domain, application use cases, adapters, interfaces, and composition root.
- `metro-station-designer` and `metro-station-visualizer` own presentation applications.
- `metro-station-experiments` owns experiment execution and evidence analysis.
- `metro-station-testkit` and `metro-station-acceptance` own quality-only code.

The legacy `sandbox.metro_station_sandbox` namespace is a forwarding compatibility layer. It may
depend on the new packages; no new package may depend on it.

## Consequences

- Each distribution has explicit dependencies and can be built independently.
- Production installation excludes experiments, testkit, acceptance, and UI assets.
- Compatibility imports resolve to the same module objects rather than duplicate implementations.
- Future removal of the compatibility namespace is mechanical and does not change behavior.
