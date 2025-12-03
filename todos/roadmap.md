# Roadmap

> **Last Updated**: 2025-12-03
> **Status Legend**: `[ ]` = Todo | `[~]` = In Progress | `[x]` = Done

---

## Critical Issues

### [ ] Observer Adapter Input Delivery

**Problem**: When user sends message in Telegram to an AI-started session, input is NOT delivered to tmux terminal.

**Root Cause**: Session started via Redis adapter (initiator), Telegram registered as observer. Message routing doesn't reach terminal for observer adapters.

**Files**: `telegram_adapter.py`, `adapter_client.py`, `terminal_bridge.py`

---

### [ ] AI-to-AI MCP Tools Availability

**Problem**: Most projects don't have TeleClaude MCP tools configured, so receiving AIs can't reply via protocol.

**Solution**: Configure TeleClaude MCP at user level (`~/.claude/settings.json`) for global availability.

---

## Architecture Simplification

### [ ] Remove AI Session Branching in Polling Coordinator

**Goal**: Replace `if is_ai_session:` branching with unified `send_output_update()` for ALL sessions.

**Changes**:
- Remove `_is_ai_to_ai_session()` function
- Remove `_send_output_chunks_ai_mode()` function
- Single code path for all session types

**Benefit**: 30% reduction in polling coordinator complexity.

---

### [ ] Architecture Cleanup

- Remove deprecated `teleclaude__get_session_status` MCP tool
- Update docs/architecture.md
- Remove unused Redis streaming configuration

---

## UX Improvements

### [ ] Live Claude Output Updates in Telegram

**Goal**: Poll `claude_session_file` instead of tmux for Claude sessions to show real-time output.

**Prerequisites**: Unified adapter architecture stable.

---

### [ ] Timestamp Filtering for Session Data

**Location**: `teleclaude/core/command_handlers.py:375`

Filter session file content by timestamp to return only recent messages.

---

## Technical Debt

### [ ] Orphan Session Cleanup Automation

Automate cleanup of orphan tmux sessions and database entries on startup and periodically.

---

### [ ] Test Coverage Expansion

**Status**: 79 test stubs created across 9 modules (see `todos/missing-tests.md`).

Priority order:
1. `test_command_handlers.py` (16 tests)
2. `test_mcp_server.py` (9 tests)
3. `test_redis_adapter.py` (6 tests)

---

## Feature Requests

### [ ] Interactive next-requirements Command

Make the command aid in establishing requirements interactively until user is satisfied.

---

### [ ] New Dev Project from Scaffolding

Create feature to start new projects from example scaffolding (tooling only, not source code).

---

## Documentation

### [ ] AI-to-AI Protocol Documentation

Create `docs/ai-to-ai-protocol.md` with full specification, message format, example flows.

---

## Priority Order

1. **CRITICAL**: Observer Adapter Input Delivery
2. **CRITICAL**: AI-to-AI MCP Tools Availability
3. **HIGH**: Remove AI Session Branching
4. **MEDIUM**: Live Claude Output Updates
5. **MEDIUM**: Test Coverage Expansion
6. **LOW**: Feature Requests & Documentation
