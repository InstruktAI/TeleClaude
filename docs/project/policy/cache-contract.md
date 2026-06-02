---
description: 'Cache contract for snapshot reads, TTL refresh, and websocket updates.'
id: 'project/policy/cache-contract'
scope: 'project'
type: 'policy'
visibility: 'public'
---

# Cache Contract — Policy

## Rules

- API reads return cached data immediately.
- Cache refresh is asynchronous and driven by TTL invalidation (presence) and cross-computer ``cluster.*`` events (state).
- Cache updates are published to WebSocket subscribers.
- Cross-computer state propagates via the unified ``cluster.*`` Redis pub/sub namespace: every state mutation publishes a typed envelope, every daemon subscribes, and the local cache is the materialized view. Today this is wired for session lifecycle (`cluster.session.*`); projects, todos, and computer-presence currently propagate via the bootstrap snapshot plus the v2 workflow_bridge — same architectural shape, staged delivery. See `project/adr/0013-unified-cluster-events` for the implementation scope per push.
- Session state is updated via events, not polling.
- Cache is read-only to API handlers; no direct DB reads in handlers.

## Rationale

- Ensures fast reads and consistent client behavior without blocking on live fetches.
- Separates read paths from refresh paths to avoid user-visible latency spikes.

## Scope

- Applies to all API handlers and cache consumers.

## Enforcement

- Verify API handlers read from cache only.
- Verify cache refresh logic is asynchronous.
- Confirm WebSocket updates originate from cache changes.

## Exceptions

- None; deviations break the cache contract.
