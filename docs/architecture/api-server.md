---
description:
  Local HTTP and WebSocket API that reads from cache and routes writes
  through the command pipeline.
id: teleclaude/architecture/api-server
scope: project
type: architecture
---

# Api Server — Architecture

## Purpose

- @docs/architecture/cache
- @docs/concept/resource-models
- @docs/reference/event-types

- Provide a resource-first API for TUI and CLI clients.

- Inputs: HTTP requests and WebSocket subscriptions.
- Outputs: cached resource snapshots and event-driven updates.

- Read endpoints return cached data immediately (local-only if cache is absent).
- Write endpoints map to explicit command objects via CommandService.
- WebSocket subscriptions drive cache interest tracking and refresh pushes.

- API handlers do not fetch remote data directly; cache owns refresh.
- Session updates are merged from local DB and cached remote summaries.

- Without cache, API serves local data only.
- WebSocket disconnects clean up subscription state.

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
