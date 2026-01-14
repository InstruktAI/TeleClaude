# Cache Contract

This document describes the cache as a single smart in-memory layer that sits between REST API calls and underlying data sources.

## Simple Architecture Overview

```mermaid
flowchart TB
  TUI[TUI (REST + WS)]
  API[REST API\n(thin, read-only)]
  CACHE[Smart Cache\n(single source of truth)]
  LOCAL[Local sources\n(DB, command handlers)]
  REMOTE[Remote sources\n(Redis adapter calls)]
  WS[WS pushes\n(from cache updates)]

  TUI --> API --> CACHE
  CACHE --> LOCAL
  CACHE --> REMOTE
  CACHE --> WS --> TUI
```

Placement:
- Cache lives inside the daemon, above adapters and below REST.
- REST never fetches. It only reads cache.
- Cache owns TTL decisions and refresh scheduling.
- WebSocket notifications originate from cache updates.

## Goals

- Always serve data from cache immediately, even if stale.
- Trigger background refresh automatically when cached data is stale.
- Expose a single, consistent policy for all data types.
- Keep API handlers simple: read from cache only.
- Publish cache updates to WebSocket clients.

## Resource Model

The cache stores only resource lists. No aggregate or composite fetches.

- Computers
- Projects
- Todos
- Sessions
- Agent availability

Views compose these resources client-side.

Identifiers:
- Project identifiers are derived from full paths, not repo metadata.

Sessions are split into two layers:
- Session summary lives in cache and refreshes on TTL.
- Session detail and live events are delivered by subscription when expanded.

## Summary - Consolidated Model

- **Single smart cache** is the only read path for REST.
- **Always serve stale**, refresh in the background based on TTL.
- **Project invalidation** uses heartbeat digests:
  - Heartbeat includes an opaque **projects digest** per computer.
  - If digest changes, peers pull the full project list once.
  - This keeps heartbeats light while ensuring fast updates.

## Policy Matrix (Source of Truth)

Only values that vary are listed. All rows inherit the global rules above.

| Resource | Scope | TTL |
| --- | --- | --- |
| Computers | Global | 60s |
| Projects | Per-computer | 24h (or longer) |
| Todos | Per-project | 5m |
| Sessions | Per-computer | 15s |
| Agent availability | Global | 30s |

## Behavior Rules (Target)

- **All REST reads go through the cache.**
- **Serve stale immediately**, then **schedule refresh** if TTL expired.
- Refresh is asynchronous and must not block API calls.
- Cache publishes updates to subscribers (WS clients).
- Projects can be long TTL because invalidation is driven by heartbeat digests.

## Invalidation Rules (Target)

- **TTL** controls refresh cadence for each resource and scope.
- **Digest changes** override TTL and trigger immediate refresh:
  - Each heartbeat includes an opaque projects digest per computer.
  - If the digest changes, refresh that computer's project list once.
- No file watching is required for remote project changes.

## Cache Responsibilities (Target)

- Accept a request for a data type and return the best cached view immediately.
- Determine staleness based on TTL matrix.
- If stale, schedule a background refresh for the relevant data scope.
- Publish updates to subscribers when refreshed.

## REST Adapter Responsibilities (Target)

- Do not fetch remote data directly.
- Read only from cache and return results.
- Subscribe to cache updates and push them to clients.
