# Remote Session Stop Event Hooks — Idea

**Date:** 2026-02-20
**Source:** Recent memory (2025-12-02)
**Priority:** High (concrete feature request)

## Summary

User outlined a hook mechanism for alerting when remote cloud sessions complete. The design pattern: hook triggers → injects standard string into tmux → interpreted as user input → triggers existing `get_session_data` tool to fetch results.

## Pattern

1. Remote session reaches stop event
2. Hook fires with payload: "session {ID} finished"
3. Hook injects into tmux as user input
4. Main session interprets the signal
5. Calls `get_session_data` to retrieve output
6. Integrates results into current context

## Why This Matters

Enables hands-free monitoring of delegated work. Main session can process results autonomously without polling or manual checks.

## Implementation Hints

- Hook mechanism already partially implemented
- `get_session_data` tool exists and works
- Tmux injection pattern already used elsewhere
- Needs: hook configuration for stop events + parser for injection payload

## Related

- Session lifecycle management
- Daemon notification architecture
- Worker-orchestrator supervision patterns
