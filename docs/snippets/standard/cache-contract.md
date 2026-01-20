---
description: Cache contract for snapshot reads, TTL refresh, and websocket updates.
id: teleclaude/standard/cache-contract
requires:
- teleclaude/architecture/cache
scope: project
type: standard
---

Standard
- All API reads return cached data immediately.
- Cache refresh happens asynchronously based on TTL and digest invalidation.
- Cache updates are published to WebSocket subscribers.
- Sessions are updated via events, not polling.