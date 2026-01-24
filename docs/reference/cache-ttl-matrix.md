---
description: TTL and scope matrix for cache refresh behavior.
id: teleclaude/reference/cache-ttl-matrix
scope: project
type: reference
---

## Required reads

- @teleclaude/architecture/cache

## What it is

- TTL and scope matrix for cache refresh behavior.

## Canonical fields

- Computers: global scope, TTL 60s.
- Projects: per-computer scope, TTL 5m.
- Todos: per-project scope, TTL 5m.
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.

## Allowed values

- TTLs are defined in seconds/minutes as listed above.

## Known caveats

- Sessions are event-driven and do not use TTL refresh.
