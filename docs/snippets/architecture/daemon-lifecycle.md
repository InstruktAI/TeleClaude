---
id: architecture/daemon-lifecycle
description: TeleClaude daemon startup/shutdown order and the background loops that keep the service running.
type: architecture
scope: project
requires:
  - adapter-client.md
  - api-server.md
  - mcp-server.md
  - output-polling.md
  - agent-hooks-outbox.md
---

# Daemon Lifecycle

## Purpose
- Owns daemon startup/shutdown ordering and keeps critical background loops running.
- Coordinates adapters, API server, MCP server, polling, and outbox delivery.

## Inputs/Outputs
- Inputs: adapter events (commands/messages), hook outbox rows, API outbox rows, system signals.
- Outputs: adapter-client actions (send/edit/delete), tmux execution, API/MCP server health and restarts.

## Invariants
- Database initializes before adapters start.
- API server starts after adapters and is wired to cache; MCP server starts in background if configured.
- Background loops (poller watch, cleanup, outbox workers, resource monitor) run until shutdown.
- Restart policies limit repeated MCP/API restarts within configured windows.

## Primary Flows
- Startup: DB init → seed cache → start adapters → start API server → optional MCP server + health watch.
- Event handling: commands route to command handlers; messages/voice/file events route to tmux or handlers.
- Shutdown: cancel background tasks → stop adapters → stop API/MCP servers → close DB.

## Failure Modes
- MCP server health checks trigger limited restarts and fallback logging.
- API server crashes schedule restart with backoff; persistent failures surface in logs.
- Outbox delivery errors are retried with backoff and lock timeouts.
