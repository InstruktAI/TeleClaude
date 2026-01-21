---
description: Local HTTP and WebSocket API that reads from cache and routes writes
  through the command pipeline.
id: teleclaude/architecture/api-server
requires:
- teleclaude/architecture/cache
- teleclaude/concept/resource-models
- teleclaude/reference/event-types
scope: project
type: architecture
---

## Purpose
- Provide a resource-first API for TUI and CLI clients.

## Inputs/Outputs
- Inputs: HTTP requests and WebSocket subscriptions.
- Outputs: cached resource snapshots and event-driven updates.

## Primary flows
- Read endpoints return cached data immediately (local-only if cache is absent).
- Write endpoints map to explicit command objects via CommandService.
- WebSocket subscriptions drive cache interest tracking and refresh pushes.

## Invariants
- API handlers do not fetch remote data directly; cache owns refresh.
- Session updates are merged from local DB and cached remote summaries.

## Failure modes
- Without cache, API serves local data only.
- WebSocket disconnects clean up subscription state.