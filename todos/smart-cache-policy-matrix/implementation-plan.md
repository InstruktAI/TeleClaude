# Implementation Plan - smart-cache-policy-matrix

## Overview

Introduce a policy matrix and a cache-owned refresh mechanism. The cache returns stale data immediately and schedules refresh based on the matrix.

## Steps

1) **Policy Matrix Definition**
   - Define a centralized matrix structure (data type, scope, TTL, warmup).
   - Document defaults for computers, projects, todos, sessions, availability.

2) **Cache Refresh Orchestrator**
   - Add a cache-level function to evaluate staleness and schedule refresh.
   - Ensure refreshes are asynchronous and non-blocking.

3) **Warmup Hook**
   - On daemon startup, execute warmup refreshes defined in the matrix.
   - Confirm projects are warmed for all peers once per startup.

4) **Refresh Sources**
   - Map each data type to a refresh source (local DB/handlers or remote calls).
   - Keep refreshers resource-only with consistent shapes.

5) **Digest Invalidation**
   - Add an opaque projects digest to heartbeats.
   - If the digest changes, schedule immediate refresh for that computer's projects.

6) **Remove Endpoint-Specific Refresh**
   - Remove or disable any per-endpoint refresh logic in REST handlers.
   - Ensure all reads flow through cache.

7) **Session Summary Boundary**
   - Ensure cache only handles session summaries.
   - Route session detail and live updates to WebSocket subscriptions.

8) **Tests**
   - Unit tests for matrix lookups and refresh scheduling.
   - Integration coverage for stale-serve + refresh behavior.

## Deliverables

- Policy matrix documented and enforced.
- Cache returns stale values and schedules refresh for all data types.
- Warmup on startup for configured data types.
