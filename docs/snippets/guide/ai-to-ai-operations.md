---
description: Recommended flow for delegating work using TeleClaude MCP tools.
id: teleclaude/guide/ai-to-ai-operations
requires:
  - reference/mcp-tools
  - concept/session-types
scope: project
type: guide
---

## Goal

- Delegate work to remote AI sessions safely and predictably.

## Preconditions

- Target computer is online and reachable.

## Steps

1. List computers to confirm the target is online.
2. List projects to select a trusted project path.
3. Start a session with a clear title and initial instruction.
4. Use `send_message` for follow-ups and `get_session_data` for status checks.
5. Stop notifications when updates are no longer needed.
6. End sessions when work completes.
7. If context is near capacity, request a summary, end, and restart fresh.

## Outputs

- Delegated work executed in a monitored remote session.

## Recovery

- If a session is unresponsive, end it and start a new one on the target.
