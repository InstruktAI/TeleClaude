---
description: 'TTL and scope matrix for cache refresh behavior.'
visibility: 'public'
---

# Cache Ttl Matrix — Spec

## What it is

- TTL and scope matrix for cache refresh behavior.

- Computers: global scope, TTL 60s.
- Projects and todos: per-computer scope, no TTL; refreshed by digest (`local/projects/teleclaude/design/architecture/redis-transport`).
- Sessions: per-computer scope, TTL infinite (event-driven).
- Agent availability: global scope, TTL 30s.

- TTLs are defined in seconds as listed above.

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

- Projects and todos are never refreshed because a cached copy aged; a peer is pulled at its first heartbeat and when its advertised digest changes.
- Sessions ignore TTL and rely solely on events.
