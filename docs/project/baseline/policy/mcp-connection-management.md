---
id: project/baseline/policy/mcp-connection-management
type: policy
scope: global
description: Architecture policy for MCP clients - tool-call filtering, connection handling, to guarantee stable connection between daemon restarts.
---

# Mcp Connection Resilience — Policy

## Rules

- MCP clients connect via `bin/mcp-wrapper.py`, not directly to the daemon.
- The wrapper must provide the mcp client zero-downtime behavior across daemon restarts and reconnects.
- Wrapper must inject `caller_session_id` into tool calls for coordination.
- When wrapper receives a `teleclaude__run_agent_command(cmd="/next-{step}")` call, it must set the contents of the `teleclaude_role` file to `builder`
- Wrapper must filter `teleclaude__*` tools for agents with roles:
  - `builder`: allow ONLY `teleclaude__get_context`.
  - no role found: ALL `teleclaude__*` tools are ALLOWED.

## Rationale

- AI agents should stay connected during daemon restarts without user intervention.
- AI agents told to execute only one atomic command should not be given `teleclaude__*` tools they don't need.

## Scope

- Applies to all MCP client connections and daemon restarts.

## Enforcement

- Ensure MCP clients use the stdio wrapper.
- Verify wrapper caches handshake responses in `logs/mcp-tools-cache.json`.
- Confirm backend proxy target is `/tmp/teleclaude.sock`.

## Exceptions

- None; bypassing the wrapper breaks resilience guarantees.
