# Session Lifecycle Tools

> **Created**: 2025-12-03
> **Status**: Requirements

## Problem Statement

Currently, AIs using TeleClaude's MCP tools can start sessions (`teleclaude__start_session`) and communicate with them (`teleclaude__send_message`, `teleclaude__get_session_data`), but they lack proper lifecycle management tools:

1. **No way to unsubscribe from notifications**: When an AI interacts with a session, it automatically registers as a listener for stop/notification events. There's no way to stop receiving these notifications without ending the target session.

2. **No way to gracefully end sessions**: When a delegated AI session has completed its work or filled its context, the calling AI has no MCP tool to terminate it. Sessions can only end via user command or internal triggers.

This creates resource leaks (listeners accumulate) and prevents proper orchestration patterns where a master AI manages the lifecycle of worker AI sessions.

## Goals

**Primary Goals**:

- Implement `teleclaude__stop_notifications` tool to unsubscribe from a session's events without ending it
- Implement `teleclaude__end_session` tool to gracefully terminate an AI session

## Non-Goals

- Modifying how listeners are automatically registered (existing behavior is correct)
- Changing the AI-to-AI protocol format
- Adding new notification event types
- Implementing session pause/resume functionality

## User Stories / Use Cases

### Story 1: Master Orchestrator Stops Monitoring Completed Workers

As a master AI orchestrating multiple worker sessions, I want to stop receiving notifications from a specific worker that has completed its task so that I can focus on remaining workers without notification clutter.

**Acceptance Criteria**:

- [ ] Can call `teleclaude__stop_notifications(computer, session_id)` to unsubscribe
- [ ] Calling AI no longer receives stop/notification events from that session
- [ ] Target session continues running unaffected
- [ ] Tool works for both local and remote sessions

### Story 2: Master AI Terminates Worker Session

As a master AI, I want to gracefully end a worker AI session that has completed its task or needs to be replaced, so that system resources are freed.

**Acceptance Criteria**:

- [ ] Can call `teleclaude__end_session(computer, session_id)` to terminate a session
- [ ] Session's tmux is closed cleanly
- [ ] Session is marked as closed in database
- [ ] Session resources are cleaned up (listeners, workspace, channels)
- [ ] Tool works for both local and remote sessions

### Story 3: Context-Full Session Replacement

As a master AI, I want to end a worker session that has filled its context and start a fresh one, maintaining proper resource management throughout the transition.

**Acceptance Criteria**:

- [ ] End session → clean termination with no resource leaks
- [ ] New session can be started immediately after
- [ ] Master AI can register as listener for the new session

## Technical Constraints

- Must follow existing MCP tool patterns in `mcp_server.py`
- Must use existing session listener infrastructure (`session_listeners.py`)
- Must use existing session cleanup utilities (`session_cleanup.py`)
- For remote sessions, must route through Redis transport (via `AdapterClient`)
- Tool naming must follow existing convention: `teleclaude__*`
- Must handle both local (`computer="local"`) and remote computer targets

## Success Criteria

How will we know this is successful?

- [ ] Both tools are registered in MCP server's `list_tools()`
- [ ] Both tools have proper MCP schema with required arguments
- [ ] Unit tests verify local session behavior
- [ ] Integration tests verify end-to-end functionality
- [ ] `make lint && make test` passes
- [ ] Tools work correctly on real multi-computer setup (rsync test)

## Open Questions

None - the implementation path is clear from the existing codebase patterns.

## References

- `teleclaude/mcp_server.py` - existing MCP tools and patterns
- `teleclaude/core/session_listeners.py` - listener registration/cleanup
- `teleclaude/core/session_cleanup.py` - session cleanup utilities
- `CLAUDE.md` - AI-to-AI collaboration protocol
