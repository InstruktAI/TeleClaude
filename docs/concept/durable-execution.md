---
description: Reliability mechanism using the Outbox pattern in SQLite.
id: concept/durable-execution
scope: global
type: concept
---

# Durable Execution — Concept

## Purpose

Ensures that commands and events are never lost, even if the daemon crashes or the network is interrupted.

## Inputs/Outputs

- Inputs: commands and hook events written to outbox tables.
- Outputs: durable processing by daemon workers.

## Primary flows

1. **rest_outbox**: Captures commands from durable clients (like `telec`). The client retries until the outbox record is acknowledged.
2. **hook_outbox**: Captures agent lifecycle events (e.g., turn completed). The `mcp-wrapper` or hook script writes to this outbox to ensure the daemon processes the event eventually.

## Invariants

- State transitions and outbox entries are committed atomically.
- Daemon workers continuously monitor outboxes for pending work.

## Failure modes

- Outbox backlog grows if workers are down or stalled.
