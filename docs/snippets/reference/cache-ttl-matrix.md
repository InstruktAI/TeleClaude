---
id: teleclaude/reference/cache-ttl-matrix
type: reference
scope: project
description: TTL and scope matrix for cache refresh behavior.
requires:
  - ../architecture/cache.md
---

Reference
- Computers: global scope, TTL 60s.
- Projects: per-computer scope, TTL 5m.
- Todos: per-project scope, TTL 5m.
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.
