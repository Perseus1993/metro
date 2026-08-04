# ADR-001: Establish `metro_station` as the Official Runtime Package

- Status: Accepted

## Context

The simulation is described as both a sandbox prototype and the official runtime, while the
distribution metadata describes a data warehouse. This makes production ownership and public
imports ambiguous.

## Decision

Create an installable `metro_station` distribution under `packages/metro_station`. The old
`sandbox.metro_station_sandbox` entry point remains a forwarding compatibility surface for one
release cycle and contains no second implementation.

## Consequences

- Production, experiments, testkit, and generated artifacts have explicit homes.
- Existing commands keep working during migration.
- The package move is mechanical and must not change simulation behavior.
