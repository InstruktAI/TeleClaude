---
id: concept/durable-execution
type: concept
scope: global
description: Reliability mechanism using the Outbox pattern in SQLite.
---

# Durable Execution

## Purpose
Ensures that commands and events are never lost, even if the daemon crashes or the network is interrupted.

## Outboxes
1. **rest_outbox**: Captures commands from durable clients (like `telec`). The client retries until the outbox record is acknowledged.
2. **hook_outbox**: Captures agent lifecycle events (e.g., turn completed). The `mcp-wrapper` or hook script writes to this outbox to ensure the daemon processes the event eventually.

## Mechanism
- **Atomic Writes**: State transitions and outbox entries are committed in a single SQLite transaction.
- **Worker Polling**: The daemon continuously monitors outboxes for pending work.
