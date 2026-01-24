---
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
id: teleclaude/standard/cache-contract
scope: project
type: standard
---

## Required reads

- @teleclaude/architecture/cache

## Rule

- API reads return cached data immediately.
- Cache refresh is asynchronous and driven by TTL/digest invalidation.
- Cache updates are published to WebSocket subscribers.
- Session state is updated via events, not polling.

## Rationale

- Ensures fast reads and consistent client behavior without blocking on live fetches.

## Scope

- Applies to all API handlers and cache consumers.

## Enforcement or checks

- Verify API handlers read from cache only.
- Verify cache refresh logic is asynchronous.
- Confirm WebSocket updates originate from cache changes.

## Exceptions or edge cases

- None; deviations break the cache contract.
