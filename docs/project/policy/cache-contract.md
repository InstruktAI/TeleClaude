---
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
id: project/policy/cache-contract
scope: project
type: policy
---

# Cache Contract — Policy

## Required reads

- @docs/project/design/cache.md

## Rules

- API reads return cached data immediately.
- Cache refresh is asynchronous and driven by TTL/digest invalidation.
- Cache updates are published to WebSocket subscribers.
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
