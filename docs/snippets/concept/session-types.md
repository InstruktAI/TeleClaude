---
id: teleclaude/concept/session-types
type: concept
scope: project
description: Human vs AI-to-AI session types and local vs remote execution modes.
requires:
  - glossary.md
---

Purpose
- Explain how TeleClaude distinguishes sessions by initiator and location.

Session types
- Human session: created from Telegram or local UI interactions.
- AI-to-AI session: created via MCP tools and can be chained across computers.

Location modes
- Local: computer="local" or the local computer name; executes without transport.
- Remote: computer set to another online computer; uses transport adapters.

Outputs
- All sessions surface in Telegram topics via UI adapters.
- AI-to-AI sessions stream output back to the initiator via transport + MCP.
