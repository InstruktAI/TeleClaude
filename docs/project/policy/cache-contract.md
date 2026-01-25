---
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
id: teleclaude/policy/cache-contract
scope: project
type: policy
---

# Cache Contract — Policy

## Required reads:

- @docs/project/architecture/cache.md

## Rule

- API reads return cached data immediately.
- Cache refresh is asynchronous and driven by TTL/digest invalidation.
- Cache updates are published to WebSocket subscribers.
- Session state is updated via events, not polling.
- Ensures fast reads and consistent client behavior without blocking on live fetches.
- Applies to all API handlers and cache consumers.
- Verify API handlers read from cache only.
- Verify cache refresh logic is asynchronous.
- Confirm WebSocket updates originate from cache changes.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- None; deviations break the cache contract.
