---
description: Daemon orchestration responsibilities, boundaries, and background services.
id: teleclaude/architecture/daemon
requires:
  - architecture/system-overview
scope: project
type: architecture
---

## Purpose

- Coordinate adapters, command handling, tmux execution, and background tasks.

## Inputs/Outputs

- Inputs: configuration, adapter events, and inbound command objects.
- Outputs: command execution, tmux orchestration, cache updates, and adapter responses.

## Invariants

- Adapter interactions flow through `AdapterClient`.
- State is persisted in SQLite and surfaced via the cache.

## Primary flows

- Initialize adapters, cache, and core services.
- Execute command objects via `CommandService`.
- Manage output polling and session cleanup.
- Run background workers (hook outbox processing, resource snapshots, MCP/APIs).

## Failure modes

- Adapter startup failures block daemon readiness.
- Background worker errors are logged and may stall dependent outputs.
