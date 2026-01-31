---
id: project/policy/mcp-connection-resilience
type: policy
scope: project
description: MCP clients connect via the stdio wrapper for zero-downtime across daemon restarts.
---

# MCP Connection Resilience — Policy

## Rules

- MCP clients connect via `bin/mcp-wrapper.py`, not directly to the daemon.
- The wrapper must provide zero-downtime behavior across daemon restarts and reconnects.
- Wrapper must inject `caller_session_id` into tool calls for coordination.
- Wrapper caches handshake responses in `logs/mcp-tools-cache.json`.
- Backend proxy target is `/tmp/teleclaude.sock`.

## Rationale

AI agents should stay connected during daemon restarts without user intervention. Direct connections break on restart and require manual reconnection.

## Scope

Applies to all MCP client connections.

## Enforcement

- Ensure MCP clients use the stdio wrapper, never a direct socket connection.
- Verify handshake cache exists and is current after daemon restart.

## Exceptions

- None; bypassing the wrapper breaks resilience guarantees.
