---
description: TTL and scope matrix for cache refresh behavior.
id: project/reference/cache-ttl-matrix
scope: project
type: reference
---

# Cache Ttl Matrix — Reference

## Required reads

- @docs/project/architecture/cache.md

## What it is

- TTL and scope matrix for cache refresh behavior.

- Computers: global scope, TTL 60s.
- Projects: per-computer scope, TTL 5m.
- Todos: per-project scope, TTL 5m.
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.

- TTLs are defined in seconds/minutes as listed above.

- Sessions are event-driven and do not use TTL refresh.

## Canonical fields

- `resource`: cache resource name (computers, projects, todos, sessions, agent_availability).
- `scope`: global, per-computer, or per-project.
- `ttl`: time-to-live duration.
- `refresh_trigger`: ttl, digest, or event-driven.

## Allowed values

- `scope`: `global`, `per-computer`, `per-project`.
- `refresh_trigger`: `ttl`, `digest`, `event`.

## Known caveats

- TTLs are defaults; digest changes can trigger earlier refreshes.
- Sessions ignore TTL and rely solely on events.
