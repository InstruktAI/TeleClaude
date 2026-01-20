---
id: teleclaude/architecture/outbox
type: architecture
scope: project
description: Durable outbox tables for API commands and agent hook events.
requires:
  - database.md
  - ../reference/event-types.md
---

Purpose
- Provide exactly-once delivery semantics for API commands and hook events.

Components
- api_outbox: stores API/CLI commands until processed by the daemon worker.
- hook_outbox: stores agent hook events until consumed by the daemon.

Primary flows
- Writers insert rows with request metadata and payload.
- Workers lock, process, and mark rows as delivered.
- Responses are recorded back onto the outbox rows.

Invariants
- Outbox rows remain until marked delivered.
- Hook receiver always writes to hook_outbox instead of invoking daemon directly.
