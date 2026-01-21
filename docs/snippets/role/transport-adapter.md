---
description: Transport adapters handle cross-computer request/response and peer discovery.
id: teleclaude/role/transport-adapter
requires:
  - teleclaude/concept/adapter-types
scope: project
type: role
---

Responsibilities

- Deliver remote requests to target computers.
- Support one-shot responses for remote requests.
- Maintain peer discovery and heartbeat data.

Boundaries

- No human-facing message rendering or UX cleanup.
