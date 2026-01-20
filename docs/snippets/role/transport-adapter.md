---
id: teleclaude/role/transport-adapter
type: role
scope: project
description: Transport adapters handle cross-computer request/response and peer discovery.
requires:
  - ../concept/adapter-types.md
---

Responsibilities
- Deliver remote requests to target computers.
- Support one-shot responses for remote requests.
- Maintain peer discovery and heartbeat data.

Boundaries
- No human-facing message rendering or UX cleanup.
