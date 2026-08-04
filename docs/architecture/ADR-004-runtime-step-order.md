# ADR-004: Preserve Runtime Step Ordering During Decomposition

- Status: Accepted

## Context

`MetroStationModel` coordinates demand, trains, facilities, movement, Goal events, progress,
metrics, and stopping. Extracting services can silently change random draws or same-tick event
ordering.

## Decision

Treat the current tick order, random draw order, person conservation, and fixed-seed semantic
fingerprints as compatibility contracts. Extract one runtime service at a time. A structural
move may not reorder phases or change domain behavior.

## Consequences

- Each extraction runs the full test suite and fixed-seed acceptance evidence.
- Intentional behavior changes require a separate ADR and separate review.
- The final Mesa model is a thin scheduler over application services.
