---
id: architecture/agent-hooks-outbox
description: Agent CLI hook ingestion via hook receiver and durable outbox delivery.
type: architecture
scope: project
requires:
  - database.md
  - event-model.md
---

# Agent Hooks Outbox

## Purpose
- Capture agent CLI hook events and deliver them reliably to the daemon.

## Inputs/Outputs
- Inputs: hook receiver stdin JSON, agent name, event type.
- Outputs: hook_outbox rows, daemon-dispatched agent events, session updates.

## Invariants
- Only a fixed set of hook event types are forwarded; others are dropped.
- Hook receiver uses the TMPDIR `teleclaude_session_id` file to link events to sessions.
- Outbox rows include retry metadata (attempts, next_attempt_at, locks).

## Primary Flows
- Hook receiver normalizes payloads and enqueues hook_outbox entries in SQLite.
- Daemon outbox worker dequeues and dispatches agent events to AdapterClient handlers.

## Failure Modes
- Invalid JSON payloads are logged and skipped.
- Delivery failures increment attempt counts and are retried with backoff.
