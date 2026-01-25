---
id: concept/multi-computer-addressing
type: concept
scope: global
description:
  How computers and sessions are addressed in a distributed TeleClaude
  network.
---

# Multi Computer Addressing — Concept

## Purpose

- Define how computers and sessions are addressed across a distributed TeleClaude network.

- Inputs: `(computer, session_id)` targeting information and transport events.
- Outputs: routed commands and session-level addressing across the network.

1. **Computer Shorthand**: Every installation has a unique `computer_name` (e.g., `macbook`, `raspi`).
2. **Global Addressing**: Sessions can be addressed using `(computer, session_id)`.
3. **Discovery**: Computers broadcast heartbeats via Redis (if enabled); the `ComputerRegistry` tracks online status and capabilities.

- **Local**: `computer="local"` bypasses the network for direct daemon interaction.
- **Remote**: Any other name triggers the `RedisTransport` to route commands to the target computer.

- `session_id`: Global UUID for the TeleClaude session.
- `native_session_id`: ID assigned by the agent environment (e.g., Claude Code's internal ID), mapped to `session_id` in the `hook_outbox`.

- `computer_name` is unique per installation.
- `(computer, session_id)` uniquely identifies a session.

- Stale registry data can route commands to offline machines.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
