# ADR-005: Version Simulation and Visualization Contracts

- Status: Accepted

## Context

Experiments, diagnostics, release gates, and the renderer currently share detailed runtime
payloads. Direct access to Mesa objects makes consumers sensitive to internal refactoring.

## Decision

Application code publishes versioned `SimulationTrace`, `FrameSnapshot`, terminal-event, and
run-summary contracts. Visualization and experiment adapters consume those contracts only.
Schema-breaking changes require a new version and an explicit compatibility reader.

## Consequences

- Runtime internals can be decomposed without rewriting consumers.
- Visualization cannot become simulation truth.
- Compatibility is tested at serialized contract boundaries.
