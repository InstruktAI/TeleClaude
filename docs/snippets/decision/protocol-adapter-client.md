---
description: Decision to route all adapter operations through AdapterClient and protocol-based
  transport.
id: teleclaude/decision/protocol-adapter-client
requires:
- teleclaude/architecture/adapter-client
scope: project
type: decision
---

Decision
- Use AdapterClient as the single hub for UI and transport adapters.
- Transport adapters implement RemoteExecutionProtocol for cross-computer orchestration.

Rationale
- Decouples MCP server from specific transports.
- Enables transport swaps without changing command handlers.
- Improves testability and consistency across message flows.

Consequences
- AdapterClient must stay stable and adapter-agnostic.
- Transport adapters must explicitly implement the protocol.