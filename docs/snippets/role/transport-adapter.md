---
id: teleclaude/role/transport-adapter
type: role
scope: project
description: Transport adapters handle cross-computer request/response and streaming.
requires:
  - ../concept/adapter-types.md
---

Responsibilities
- Deliver remote requests to target computers.
- Stream session output back to callers.
- Maintain peer discovery and heartbeat data.

Boundaries
- No human-facing message rendering or UX cleanup.
