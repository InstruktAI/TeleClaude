---
id: teleclaude/policy/mcp-connection-resilience
type: policy
scope: project
description: MCP wrapper provides zero-downtime restarts and clients should not require reconnects.
requires:
  - ../architecture/mcp-layer.md
---

Policy
- MCP clients must remain connected through daemon restarts; the wrapper owns reconnection.
- The wrapper serves cached handshake/tool metadata while the backend is down.
- Do not add client behavior that assumes MCP restarts are a normal workflow step.
