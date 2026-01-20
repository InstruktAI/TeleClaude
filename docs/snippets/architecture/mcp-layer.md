---
id: architecture/mcp-layer
type: architecture
scope: global
description: Resilient two-layer MCP architecture for AI-to-AI communication.
---

# MCP Layer Architecture

## Layers
1. **Resilient Proxy (`bin/mcp-wrapper.py`)**:
   - Runs as the stdio entrypoint for MCP clients.
   - Connects to the daemon via Unix socket.
   - Provides cached handshakes and auto-reconnection.
   - Injects `caller_session_id` into tool calls.
2. **Backend Server (`teleclaude/mcp_server.py`)**:
   - Actual tool implementations using the `mcp` SDK.
   - Integrated into the main daemon process.
   - Shares the database and Redis transport.

## Data Flow
```
MCP Client (Claude) <-> Stdio Wrapper <-> Unix Socket <-> Daemon Backend <-> Command Pipeline
```

## Resilience Pattern
If the daemon restarts (`make restart`), the wrapper stays alive and buffers requests until the socket is available again, ensuring zero-downtime for the AI client.