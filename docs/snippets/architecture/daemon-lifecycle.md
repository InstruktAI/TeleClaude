---
id: teleclaude/architecture/daemon-lifecycle
type: architecture
scope: project
description: Daemon startup, background task orchestration, and graceful shutdown behavior.
requires:
  - system-overview.md
  - mcp-layer.md
  - api-server.md
---

Purpose
- Describe how the daemon starts, monitors, and shuts down core services.

Primary flows
- Initialize AdapterClient, cache, agent coordinator, and output poller.
- Start adapters, API server, and MCP server tasks.
- Watch MCP socket health and restart MCP server on failure.
- Run background workers for outbox processing and resource snapshots.

Invariants
- Background tasks are tracked and logged on failure.
- MCP restarts are rate-limited to avoid restart storms.

Failure modes
- Adapter startup failure prevents daemon boot.
- MCP server failures trigger automatic restart attempts.
