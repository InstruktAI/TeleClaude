---
description: TTL and scope matrix for cache refresh behavior.
id: teleclaude/reference/cache-ttl-matrix
requires:
- teleclaude/architecture/cache
scope: project
type: reference
---

Reference
- Computers: global scope, TTL 60s.
- Projects: per-computer scope, TTL 5m.
- Todos: per-project scope, TTL 5m.
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.