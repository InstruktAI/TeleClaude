---
description: Transport adapters handle cross-computer request/response and peer discovery.
id: teleclaude/architecture/transport-adapter
requires:
  - teleclaude/concept/adapter-types
scope: project
type: architecture
---

Responsibilities

- Deliver remote requests to target computers.
- Support one-shot responses for remote requests.
- Maintain peer discovery and heartbeat data.

Boundaries

- No human-facing message rendering or UX cleanup.
