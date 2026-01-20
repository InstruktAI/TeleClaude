---
id: architecture/mcp-server
description: MCP tool server exposing TeleClaude operations over a local socket and remote relay.
type: architecture
scope: project
requires:
  - adapter-client.md
  - redis-transport.md
  - session-lifecycle.md
---

# MCP Server

## Purpose
- Expose TeleClaude tools (teleclaude__*) to AI agents via MCP.

## Inputs/Outputs
- Inputs: MCP JSON-RPC requests, tool list requests, session data queries.
- Outputs: tool responses, remote request forwarding, tool list change notifications.

## Invariants
- Tool signatures are tracked across restarts; changes trigger list_changed notification windows.
- Local computer operations are handled directly; remote operations are routed through AdapterClient.
- Session data responses are capped by `MCP_SESSION_DATA_MAX_CHARS`.

## Primary Flows
- Start: serve MCP over the configured socket and accept concurrent connections.
- Tool execution: dispatch to handlers or send remote requests and await response envelopes.
- Listener registration: register session stop listeners when sessions are touched.

## Failure Modes
- Client disconnects are handled without crashing the server.
- Remote request timeouts or invalid JSON raise RemoteRequestError.
