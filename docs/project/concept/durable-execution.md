---
description: Reliability mechanism using the Outbox pattern in SQLite.
id: concept/durable-execution
scope: global
type: concept
---

# Durable Execution — Concept

## Purpose

Ensures that commands and events are never lost, even if the daemon crashes or the network is interrupted.

- **rest_outbox**: captures commands from durable clients; clients retry until acknowledged.
- **hook_outbox**: captures agent lifecycle events written by hook scripts or wrappers.

- State transitions and outbox entries are committed atomically.
- Daemon workers continuously monitor outboxes for pending work.

- Outbox backlog grows if workers are down or stalled.

## Inputs/Outputs

- **Inputs**: commands and hook events written to outbox tables.
- **Outputs**: durable processing by daemon workers.

## Invariants

- Outbox writes are transactional with state updates.
- Entries are processed at-least-once until marked delivered.

## Primary flows

- Client writes command → outbox row → daemon worker executes → mark delivered.
- Hook writes event → outbox row → daemon worker handles → mark delivered.

## Failure modes

- Worker stalls cause backlog growth and delayed processing.
- Lock contention can slow delivery; retries handle contention.
