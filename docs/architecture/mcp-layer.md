---
id: architecture/mcp-layer
type: architecture
scope: global
description: Resilient two-layer MCP architecture for AI-to-AI communication.
---

## Purpose

- Provide a resilient MCP interface for AI-to-AI communication.
- Preserve tool contract stability across daemon restarts.

## Inputs/Outputs

- Inputs: MCP tool calls from AI clients.
- Outputs: tool responses routed through the daemon command pipeline.

## Invariants

- Clients connect via `bin/mcp-wrapper.py` (stdio entrypoint).
- Wrapper connects to the daemon via Unix socket and injects `caller_session_id`.
- Handshake responses are cached to avoid client restarts during daemon reconnects.

## Primary flows

- MCP Client ↔ Stdio Wrapper ↔ Unix Socket ↔ Daemon Backend ↔ Command Pipeline.
- Wrapper returns cached handshake responses while backend reconnects.

## Failure modes

- If the backend is unavailable, wrapper buffers/awaits until the socket returns.
- If the socket is unavailable, the wrapper retries without requiring client restart.
