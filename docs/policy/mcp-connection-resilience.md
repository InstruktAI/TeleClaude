---
id: policy/mcp-connection-resilience
type: policy
scope: global
description: Architecture policy for MCP connection handling and zero-downtime restarts.
---

# Mcp Connection Resilience — Policy

## Rule

- MCP clients connect via `bin/mcp-wrapper.py`, not directly to the daemon.
- The wrapper must provide zero-downtime behavior across restarts and reconnects.

- AI agents should stay connected during daemon restarts without user intervention.

- Applies to all MCP client connections and daemon restarts.

- Ensure MCP clients use the stdio wrapper.
- Verify wrapper caches handshake responses in `logs/mcp-tools-cache.json`.
- Confirm backend proxy target is `/tmp/teleclaude.sock`.

- None; bypassing the wrapper breaks resilience guarantees.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
