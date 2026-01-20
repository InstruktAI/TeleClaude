---
id: teleclaude/architecture/outbox
type: architecture
scope: project
description: Durable outbox table for agent hook events.
requires:
  - database.md
  - ../reference/event-types.md
---

Purpose
- Provide durable delivery semantics for agent hook events.

Components
- hook_outbox: stores agent hook events until consumed by the daemon.

Primary flows
- Hook receiver inserts rows with normalized payloads.
- Daemon locks, processes, and marks rows as delivered.

Invariants
- Outbox rows remain until marked delivered.
- Hook receiver always writes to hook_outbox instead of invoking daemon directly.
