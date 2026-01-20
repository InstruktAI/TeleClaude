---
id: policy/mcp-connection-resilience
type: policy
scope: global
description: Architecture policy for MCP connection handling and zero-downtime restarts.
---

# MCP Connection Resilience Policy

## Purpose
Ensures that AI agents (Claude Code, Gemini, etc.) remain connected to TeleClaude tools even during daemon restarts or network flickers.

## Guarantees
1. **Zero-Downtime**: Clients experience no disconnection during `make restart`.
2. **Transparent Recovery**: The `mcp-wrapper.py` handles all reconnection logic automatically.
3. **Static Handshake**: The wrapper responds to initialization immediately using cached capabilities if the backend is temporarily down.

## Implementation Invariants
- Clients MUST connect to the `stdio` wrapper (`bin/mcp-wrapper.py`).
- The wrapper proxies requests to the backend Unix socket (`/tmp/teleclaude.sock`).
- Handshake responses are cached in `logs/mcp-tools-cache.json`.