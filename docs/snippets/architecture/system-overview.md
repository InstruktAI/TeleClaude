---
id: teleclaude/architecture/system-overview
type: architecture
scope: project
description: High-level component map of TeleClaude daemon, adapters, transport, and storage.
requires:
  - ../concept/adapter-types.md
  - ../concept/resource-models.md
---

Purpose
- Provide a mental model of TeleClaude's major components and boundaries.

Components
- Daemon core: command execution, tmux orchestration, output polling, event routing.
- AdapterClient: unified interface to UI adapters and transport adapters.
- UI adapters: Telegram messaging and topic management.
- Transport adapters: Redis Streams for cross-computer request/response.
- MCP server + wrapper: AI tool interface over a local UNIX socket with resilience.
- API server: local HTTP/WS interface for TUI and CLI.
- SQLite database: sessions, outbox records, UX state, agent data.
- Cache: snapshot layer for computers/projects/todos/sessions.

Primary flows
- Ingress from Telegram/MCP/API -> command mappers -> CommandService -> tmux -> output polling -> AdapterClient -> UI.
- Remote requests use transport adapters; output retrieval is via MCP get_session_data polling.

Failure modes
- Adapter startup failures prevent daemon boot.
- Transport outages degrade cross-computer features but local sessions continue.
