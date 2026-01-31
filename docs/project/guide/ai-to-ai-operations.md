---
description: Recommended flow for delegating work using TeleClaude MCP tools.
id: project/guide/ai-to-ai-operations
scope: project
type: guide
---

# AI-to-AI Operations — Guide

## Required reads

- @docs/project/reference/command-surface.md
- @docs/project/reference/command-contracts.md

## Goal

Delegate work to remote AI sessions safely and predictably.

## Context

TeleClaude provides MCP tools that let a master AI start sessions on remote computers, send messages, monitor progress, and clean up. Sessions started this way get AI-to-AI title formatting and faster polling. The master AI is responsible for the full lifecycle of delegated sessions.

## Approach

1. List computers to confirm the target is online.
2. List projects to select a trusted project path.
3. Start a session with a clear title and initial instruction.
4. Use `send_message` for follow-ups and `get_session_data` for status checks.
5. Stop notifications when updates are no longer needed.
6. End sessions when work completes.
7. If context is near capacity, request a summary, end, and restart fresh.

## Pitfalls

- Forgetting to end sessions — orphaned sessions consume resources and confuse monitoring.
- Polling too aggressively with `get_session_data` — respect the 5-minute cadence gate.
- Starting sessions on computers or project paths that aren't in `trusted_dirs` — the command will be rejected.
