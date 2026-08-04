# ADR-003: Separate Station Schema, Compilation, and Validation

- Status: Accepted

## Context

Design validation currently imports station graph compilation, while station compilation
imports design validation. Geometry and topology checks are also mixed.

## Decision

Use a one-way pipeline:

```text
StationDesignDocument
  -> SchemaValidator
  -> GeometryValidator
  -> StationGraphCompiler
  -> TopologyValidator
  -> RuntimeLayoutCompiler
```

Schema validation cannot import `StationGraph`. Topology validation operates on an already
compiled graph. Renderer constants are not design inputs.

## Consequences

- Design documents can be validated without recursively invoking the compiler.
- Topology diagnostics remain authoritative but move to the application compilation boundary.
- Built-in layouts must retain their existing graph fingerprints.
