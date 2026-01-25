---
description: TTL and scope matrix for cache refresh behavior.
id: teleclaude/reference/cache-ttl-matrix
scope: project
type: reference
---

# Cache Ttl Matrix — Reference

## What it is

- @docs/architecture/cache

- TTL and scope matrix for cache refresh behavior.

- Computers: global scope, TTL 60s.
- Projects: per-computer scope, TTL 5m.
- Todos: per-project scope, TTL 5m.
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.

- TTLs are defined in seconds/minutes as listed above.

- Sessions are event-driven and do not use TTL refresh.

- TBD.

- TBD.

- TBD.

## Canonical fields

- TBD.

## Allowed values

- TBD.

## Known caveats

- TBD.
