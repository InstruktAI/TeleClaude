---
description: Recommended flow for delegating work using TeleClaude MCP tools.
id: project/procedure/ai-to-ai-operations
scope: project
type: procedure
---

# AI-to-AI Operations — Procedure

## Required reads

- @docs/project/spec/command-surface.md
- @docs/project/spec/command-contracts.md

## Goal

Delegate work to remote AI sessions safely and predictably.

## Preconditions

- Target computer is online and listed in trusted dirs.
- You have a clear task and title for the delegated session.

## Steps

1. List computers to confirm the target is online.
2. List projects to select a trusted project path.
3. Start a session with a clear title and initial instruction.
4. Use `send_message` for follow-ups and `get_session_data` for status checks.
5. Stop notifications when updates are no longer needed.
6. End sessions when work completes.
7. If context is near capacity, request a summary, end, and restart fresh.

## Outputs

- Delegated session running with monitoring in place.
- Session closed and cleaned up when work completes.

## Recovery

- Forgetting to end sessions — orphaned sessions consume resources and confuse monitoring.
- Polling too aggressively with `get_session_data` — respect the 5-minute cadence gate.
- Starting sessions on computers or project paths that aren't in `trusted_dirs` — the command will be rejected.
