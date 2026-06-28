# ADR 0001: Framework-light Agent Core

## Status

Accepted.

## Context

The learning and product goal requires direct understanding and ownership of the Agent Loop,
tool contract, policy decisions, and persisted state.

## Decision

The core will not depend on LangGraph or another Agent orchestration framework. Mature
libraries remain appropriate for validation, HTTP, CLI, storage, and testing. Optional
workflow integrations may be added outside the core.

## Consequences

- State transitions and failure semantics remain explicit and testable.
- Provider and tool contracts belong to this project.
- The project carries the cost of maintaining the loop and persistence model.
- Framework-specific integrations cannot bypass policy, trace, or session boundaries.
