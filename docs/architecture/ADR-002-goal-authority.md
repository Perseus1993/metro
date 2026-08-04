# ADR-002: Goal Graph Remains the Sole Strategic Authority

- Status: Accepted

## Context

Passengers need strategic journey decisions and short-lived physical movement targets. Mixing
these responsibilities creates competing state machines and ambiguous terminal authority.

## Decision

Goal Graph owns strategic facility choice, commitment, waiting, replanning, and terminal
completion. `AgentPlan` remains a temporary physical-goal adapter. Pure Goal state machines
consume immutable events and observations and emit commands; adapters execute those commands.

## Consequences

- Mesa and JuPedSim are replaceable adapters around the Goal domain.
- Only an authorized Goal completion command may create a terminal event.
- Domain tests run without simulation dependencies.
