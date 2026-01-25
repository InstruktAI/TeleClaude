---
description: Event-driven read-cache architecture using SQLite snapshots.
id: architecture/cache-system
scope: project
type: architecture
---

# Cache System — Architecture

## Purpose

Provides sub-millisecond read access to system state (computers, sessions, projects, todos) for TUIs and high-frequency callers.

```mermaid
flowchart TB
  TUI["TUI (API + WS)"]
  API["API<br/>(thin, read-only)"]
  CACHE["Snapshot Cache<br/>(read-only)"]
  LOCAL["Local sources<br/>(DB, command handlers)"]
  EVENTS["Domain events<br/>(from core)"]
  WS["WS pushes<br/>(from cache updates)"]

  TUI --> API --> CACHE
  CACHE --> LOCAL
  EVENTS --> CACHE
  CACHE --> WS --> TUI
```

- Inputs: domain events and local data sources (DB, command handlers).
- Outputs: snapshot reads and WebSocket update notifications.

1. **Snapshots**: The cache stores JSON snapshots of domain objects in a dedicated `cache` table.
2. **Read-Only**: The cache is NOT a source of truth; it is a materialized view of the database and runtime state.
3. **Event-Driven**: Updates are triggered by domain events (e.g., `SessionCreated`, `ComputerHeartbeat`).
4. **Warmup**: The cache is fully populated on daemon startup.

- Clients (TUI, API) SHOULD read from the cache and write via commands.
- Cache handlers MUST NOT perform complex I/O; they merely transform events into snapshots.

- Stale snapshots may be served until refresh completes.

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
