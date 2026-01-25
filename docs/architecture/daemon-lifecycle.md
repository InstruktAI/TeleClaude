---
description:
  Daemon startup, background task orchestration, and graceful shutdown
  behavior.
id: teleclaude/architecture/daemon-lifecycle
scope: project
type: architecture
---

# Daemon Lifecycle — Architecture

## Purpose

- @docs/architecture/system-overview
- @docs/architecture/mcp-layer
- @docs/architecture/api-server

- Describe how the daemon starts, monitors, and shuts down core services.

- Inputs: configuration, system resources, and startup commands.
- Outputs: running adapters, servers, and background workers.

- Initialize AdapterClient, cache, agent coordinator, and output poller.
- Start adapters, API server, and MCP server tasks.
- Watch MCP socket health and restart MCP server on failure.
- Run background workers for hook outbox processing and resource snapshots.

- Background tasks are tracked and logged on failure.
- MCP restarts are rate-limited to avoid restart storms.

- Adapter startup failure prevents daemon boot.
- MCP server failures trigger automatic restart attempts.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
