---
id: teleclaude/role/daemon
type: role
scope: project
description: The daemon coordinates adapters, command handling, tmux execution, and background tasks.
requires:
  - ../architecture/system-overview.md
---

Responsibilities
- Initialize adapters, cache, and core services.
- Execute command objects via CommandService.
- Manage output polling and session cleanup.
- Run background workers (outbox processing, resource snapshots, MCP/APIs).

Boundaries
- Uses AdapterClient for all adapter interactions.
- Persists state in SQLite and publishes updates via cache.
