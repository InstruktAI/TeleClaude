---
id: teleclaude/architecture/mcp-layer
type: architecture
scope: project
description: Two-layer MCP interface (wrapper + server) that exposes TeleClaude tools with zero-downtime restarts.
requires:
  - ../architecture/adapter-client.md
  - ../architecture/redis-transport.md
  - ../architecture/session-lifecycle.md
  - ../architecture/context-selection.md
---

Purpose
- Expose TeleClaude operations to AI agents through MCP tools.

Components
- mcp-wrapper (bin/mcp-wrapper.py): resilient proxy with cached handshake and auto-reconnect.
- MCP server (teleclaude/mcp_server.py): tool implementation backed by AdapterClient.

Primary flows
- Client connects over stdio -> wrapper -> UNIX socket -> MCP server.
- Tool calls are routed to local command handlers or remote transport requests.
- Session output streaming is delivered via Redis output streams.

Invariants
- Wrapper responds to initialize even when backend restarts.
- Tool list is cached on disk and served only while backend is down.
- caller_session_id is injected into tool calls when available.

Failure modes
- If backend is down, wrapper serves cached handshake and waits for reconnect.
- Remote requests time out when target computer is offline.
