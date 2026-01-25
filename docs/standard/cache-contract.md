---
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
id: teleclaude/standard/cache-contract
scope: project
type: standard
---

# Cache Contract — Standard

## Rule

- @docs/architecture/cache

- API reads return cached data immediately.
- Cache refresh is asynchronous and driven by TTL/digest invalidation.
- Cache updates are published to WebSocket subscribers.
- Session state is updated via events, not polling.

- Ensures fast reads and consistent client behavior without blocking on live fetches.

- Applies to all API handlers and cache consumers.

- Verify API handlers read from cache only.
- Verify cache refresh logic is asynchronous.
- Confirm WebSocket updates originate from cache changes.

- None; deviations break the cache contract.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
