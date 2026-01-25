---
description: Daemon orchestration responsibilities, boundaries, and background services.
id: teleclaude/architecture/daemon
scope: project
type: architecture
---

# Daemon — Architecture

## Purpose

- @docs/architecture/system-overview

- Coordinate adapters, command handling, tmux execution, and background tasks.

- Inputs: configuration, adapter events, and inbound command objects.
- Outputs: command execution, tmux orchestration, cache updates, and adapter responses.

- Adapter interactions flow through `AdapterClient`.
- State is persisted in SQLite and surfaced via the cache.

- Initialize adapters, cache, and core services.
- Execute command objects via `CommandService`.
- Manage output polling and session cleanup.
- Run background workers (hook outbox processing, resource snapshots, MCP/APIs).

- Adapter startup failures block daemon readiness.
- Background worker errors are logged and may stall dependent outputs.

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
