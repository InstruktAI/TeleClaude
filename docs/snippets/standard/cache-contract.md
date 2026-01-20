---
id: teleclaude/standard/cache-contract
type: standard
scope: project
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
requires:
  - ../architecture/cache.md
---

Standard
- All API reads return cached data immediately.
- Cache refresh happens asynchronously based on TTL and digest invalidation.
- Cache updates are published to WebSocket subscribers.
- Sessions are updated via events, not polling.
