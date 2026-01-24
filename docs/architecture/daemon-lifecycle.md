---
description:
  Daemon startup, background task orchestration, and graceful shutdown
  behavior.
id: teleclaude/architecture/daemon-lifecycle
scope: project
type: architecture
---

## Required reads

- @architecture/system-overview
- @architecture/mcp-layer
- @teleclaude/architecture/api-server

## Purpose

- Describe how the daemon starts, monitors, and shuts down core services.

## Inputs/Outputs

- Inputs: configuration, system resources, and startup commands.
- Outputs: running adapters, servers, and background workers.

## Primary flows

- Initialize AdapterClient, cache, agent coordinator, and output poller.
- Start adapters, API server, and MCP server tasks.
- Watch MCP socket health and restart MCP server on failure.
- Run background workers for hook outbox processing and resource snapshots.

## Invariants

- Background tasks are tracked and logged on failure.
- MCP restarts are rate-limited to avoid restart storms.

## Failure modes

- Adapter startup failure prevents daemon boot.
- MCP server failures trigger automatic restart attempts.
