---
id: teleclaude/architecture/daemon
type: architecture
scope: project
description: Daemon orchestration responsibilities, boundaries, and background services.
requires:
  - system-overview.md
---

Purpose
- Coordinate adapters, command handling, tmux execution, and background tasks.

Responsibilities
- Initialize adapters, cache, and core services.
- Execute command objects via CommandService.
- Manage output polling and session cleanup.
- Run background workers (hook outbox processing, resource snapshots, MCP/APIs).

Boundaries
- Uses AdapterClient for all adapter interactions.
- Persists state in SQLite and publishes updates via cache.
